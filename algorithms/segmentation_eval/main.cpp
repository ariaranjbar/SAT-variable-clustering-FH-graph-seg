#include <iostream>
#include <string>
#include <vector>
#include <limits>
#include <sstream>
#include <algorithm>
#include <cctype>
#include <cstdint>

#include "thesis/cli.hpp"
#include "thesis/timer.hpp"
#include "thesis/cnf.hpp"
#include "thesis/vig.hpp"
#include "thesis/segmentation.hpp"
#include "thesis/modularity.hpp"
#include "thesis/comp_metrics.hpp"
#include "thesis/csv.hpp"

using namespace thesis;

static std::vector<double> parse_double_list(const std::string &s, const char* label) {
    // Accept comma-separated list of doubles, also accept a single value.
    std::vector<double> ks;
    std::string tok;
    std::stringstream ss(s);
    while (std::getline(ss, tok, ',')) {
        if (tok.empty()) continue;
        try {
            ks.push_back(std::stod(tok));
        } catch (...) {
            throw std::runtime_error(std::string("invalid ") + label + " value: " + tok);
        }
    }
    if (ks.empty()) throw std::runtime_error(std::string("no valid ") + label + " provided");
    return ks;
}

static std::vector<unsigned long long> parse_uint64_list(const std::string& s, const char* label) {
    std::vector<unsigned long long> out;
    std::string tok; std::stringstream ss(s);
    while (std::getline(ss, tok, ',')) {
        if (tok.empty()) continue;
        try { out.push_back(static_cast<unsigned long long>(std::stoull(tok))); }
        catch (...) { throw std::runtime_error(std::string("invalid ") + label + " value: " + tok); }
    }
    if (out.empty()) throw std::runtime_error(std::string("no valid ") + label + " provided");
    return out;
}

static std::vector<bool> parse_bool_list(const std::string& s, const char* label) {
    std::vector<bool> out;
    std::string tok; std::stringstream ss(s);
    while (std::getline(ss, tok, ',')) {
        if (tok.empty()) continue;
        std::string t; t.reserve(tok.size());
        for (char c : tok) t.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
        if (t == "1" || t == "true" || t == "on" || t == "yes") out.push_back(true);
        else if (t == "0" || t == "false" || t == "off" || t == "no") out.push_back(false);
        else throw std::runtime_error(std::string("invalid ") + label + " value: " + tok);
    }
    if (out.empty()) throw std::runtime_error(std::string("no valid ") + label + " provided");
    return out;
}

static std::vector<std::string> parse_string_list(const std::string& s, const char* label) {
    std::vector<std::string> out; std::string tok; std::stringstream ss(s);
    while (std::getline(ss, tok, ',')) { if (!tok.empty()) out.push_back(tok); }
    if (out.empty()) throw std::runtime_error(std::string("no valid ") + label + " provided");
    return out;
}

int main(int argc, char **argv) {
    ArgParser cli("Build VIG once (tau=inf and tau=user), segment on user VIG for multiple k, reuse labels on tau=inf VIG to compute modularity.");
    cli.add_option(OptionSpec{.longName = "input", .shortName = 'i', .type = ArgType::String, .valueName = "FILE|-", .help = "Path to DIMACS CNF or '-' for stdin", .required = true});
    cli.add_option(OptionSpec{.longName = "tau", .shortName = '\0', .type = ArgType::UInt64, .valueName = "N|inf", .help = "Clause size threshold for user VIG; 'inf' for no limit", .required = false, .defaultValue = "inf", .allowInfToken = true});
    cli.add_option(OptionSpec{.longName = "out-csv", .shortName = '\0', .type = ArgType::String, .valueName = "FILE", .help = "Path to output CSV (required)", .required = true, .defaultValue = ""});
    cli.add_option(OptionSpec{.longName = "k", .shortName = 'k', .type = ArgType::String, .valueName = "K[,K2,...]", .help = "Segmentation parameter(s); comma-separated doubles", .required = false, .defaultValue = std::to_string(GraphSegmenterFH::kDefaultK)});
    cli.add_flag("naive", '\0', "Use naive VIG builder (single-threaded)");
    cli.add_flag("opt", '\0', "Use optimized VIG builder (default)");
    cli.add_option(OptionSpec{.longName = "threads", .shortName = 't', .type = ArgType::UInt64, .valueName = "N", .help = "Threads for optimized VIG build (0=auto)", .required = false, .defaultValue = "0"});
    cli.add_option(OptionSpec{.longName = "maxbuf", .shortName = '\0', .type = ArgType::Size, .valueName = "BYTES", .help = "Max buffer for optimized VIG build", .required = false, .defaultValue = "50000000"});

    // Sweepable segmentation knobs
    // Booleans: offer list-style options; if not provided, derive from single flags where applicable.
    cli.add_option(OptionSpec{.longName = "size-exp", .shortName = '\0', .type = ArgType::String, .valueName = "E[,..]", .help = "Size exponent(s) in gate denominator", .required = false, .defaultValue = std::to_string(GraphSegmenterFH::Config::kDefaultSizeExponent)});
    cli.add_option(OptionSpec{.longName = "mod-guard", .shortName = '\0', .type = ArgType::String, .valueName = "on|off[,..]", .help = "List of modularity guard settings (on/off)", .required = false, .defaultValue = ""});
    cli.add_flag("no-mod-guard", '\0', "Disable modularity guard in segmentation (single toggle if --mod-guard not provided)");
    cli.add_option(OptionSpec{.longName = "gamma", .shortName = '\0', .type = ArgType::String, .valueName = "G[,..]", .help = "Modularity resolution(s) for guard", .required = false, .defaultValue = std::to_string(GraphSegmenterFH::Config::kDefaultGamma)});
    cli.add_option(OptionSpec{.longName = "anneal", .shortName = '\0', .type = ArgType::String, .valueName = "on|off[,..]", .help = "List of annealing settings (on/off)", .required = false, .defaultValue = ""});
    cli.add_flag("no-anneal-guard", '\0', "Disable annealing of ΔQ tolerance (single toggle if --anneal not provided)");
    {
        std::ostringstream oss; oss << GraphSegmenterFH::Config::kDefaultDqTolerance0; // preserves scientific notation if any
        cli.add_option(OptionSpec{.longName = "dq-tol0", .shortName = '\0', .type = ArgType::String, .valueName = "T[,..]", .help = "Initial ΔQ tolerance list", .required = false, .defaultValue = oss.str()});
    }
    cli.add_option(OptionSpec{.longName = "dq-vscale", .shortName = '\0', .type = ArgType::String, .valueName = "S[,..]", .help = "ΔQ anneal scale list (0 => auto)", .required = false, .defaultValue = std::to_string(GraphSegmenterFH::Config::kDefaultDqVscale)});
    {
        // Translate default ambiguous policy enum to string
        std::string ambDef = (GraphSegmenterFH::Config::kDefaultAmbiguousPolicy == GraphSegmenterFH::Config::Ambiguous::Accept) ? "accept" :
                             (GraphSegmenterFH::Config::kDefaultAmbiguousPolicy == GraphSegmenterFH::Config::Ambiguous::Reject) ? "reject" : "margin";
        cli.add_option(OptionSpec{.longName = "ambiguous", .shortName = '\0', .type = ArgType::String, .valueName = "accept|reject|margin[,..]", .help = "Ambiguous policy list", .required = false, .defaultValue = ambDef});
    }
    {
        std::ostringstream oss; oss << GraphSegmenterFH::Config::kDefaultGateMarginRatio;
        cli.add_option(OptionSpec{.longName = "gate-margin", .shortName = '\0', .type = ArgType::String, .valueName = "R[,..]", .help = "Gate margin ratio list for 'margin' policy", .required = false, .defaultValue = oss.str()});
    }

    bool proceed = true;
    try { proceed = cli.parse(argc, argv); } catch (const std::exception &e) {
        std::cerr << cli.usage(argv[0]) << "\n" << e.what() << "\n";
        return 1;
    }
    if (!proceed) { std::cout << cli.help(argv[0]); return 0; }

    const std::string path = cli.get_string("input");
    const unsigned tau_user = static_cast<unsigned>(cli.get_uint64("tau"));
    const bool use_naive = cli.get_flag("naive");
    bool use_opt = cli.get_flag("opt");
    if (!use_naive && !use_opt) use_opt = true;
    const unsigned threads = static_cast<unsigned>(cli.get_uint64("threads"));
    const std::size_t maxbuf = cli.get_size("maxbuf");

    std::vector<double> k_values;
    try { k_values = parse_double_list(cli.get_string("k"), "k"); } catch (const std::exception &e) { std::cerr << e.what() << "\n"; return 1; }

    // Build sweep lists for segmentation configuration
    // size-exp
    std::vector<double> size_exps;
    try { size_exps = parse_double_list(cli.get_string("size-exp"), "size-exp"); } catch (const std::exception&) {
        size_exps = { GraphSegmenterFH::Config::kDefaultSizeExponent }; // single fallback referencing centralized default
    }
    // mod-guard
    std::vector<bool> mod_guards;
    if (cli.provided("mod-guard")) {
        try { mod_guards = parse_bool_list(cli.get_string("mod-guard"), "mod-guard"); } catch (const std::exception& e) { std::cerr << e.what() << "\n"; return 1; }
    } else {
        const bool base = GraphSegmenterFH::Config::kDefaultUseModularityGuard;
        mod_guards = { cli.get_flag("no-mod-guard") ? false : base };
    }
    // gamma
    std::vector<double> gammas;
    try { gammas = parse_double_list(cli.get_string("gamma"), "gamma"); } catch (const std::exception&) {
        gammas = { GraphSegmenterFH::Config::kDefaultGamma };
    }
    // anneal
    std::vector<bool> anneals;
    if (cli.provided("anneal")) {
        try { anneals = parse_bool_list(cli.get_string("anneal"), "anneal"); } catch (const std::exception& e) { std::cerr << e.what() << "\n"; return 1; }
    } else {
        const bool base = GraphSegmenterFH::Config::kDefaultAnnealModularityGuard;
        anneals = { cli.get_flag("no-anneal-guard") ? false : base };
    }
    // dq-tol0
    std::vector<double> dq_tols;
    try { dq_tols = parse_double_list(cli.get_string("dq-tol0"), "dq-tol0"); } catch (const std::exception&) {
        dq_tols = { GraphSegmenterFH::Config::kDefaultDqTolerance0 };
    }
    // dq-vscale
    std::vector<double> dq_vscales;
    try { dq_vscales = parse_double_list(cli.get_string("dq-vscale"), "dq-vscale"); } catch (const std::exception&) {
        dq_vscales = { GraphSegmenterFH::Config::kDefaultDqVscale };
    }
    // ambiguous
    std::vector<std::string> ambs;
    try { ambs = parse_string_list(cli.get_string("ambiguous"), "ambiguous"); } catch (const std::exception&) {
        ambs = { cli.get_string("ambiguous") };
    }
    // gate-margin
    std::vector<double> gate_margins;
    try { gate_margins = parse_double_list(cli.get_string("gate-margin"), "gate-margin"); } catch (const std::exception&) {
        gate_margins = { GraphSegmenterFH::Config::kDefaultGateMarginRatio };
    }

    // Helper to lower-case strings for policy checks
    auto to_lower = [](std::string s){
        std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c){ return static_cast<char>(std::tolower(c)); });
        return s;
    };

    // Parse CNF once
    Timer t_total;
    Timer t_parse;
    CNF cnf = (path == "-") ? CNF(std::cin, /*variable_compaction=*/true)
                              : CNF(path, /*variable_compaction=*/true);
    const double sec_parse = t_parse.sec();
    if (!cnf.is_valid()) { std::cerr << "Failed to parse CNF: " << path << "\n"; return 2; }

    const uint32_t nvars = cnf.get_variable_count();
    const std::string out_csv = cli.get_string("out-csv");

    // Build VIG with tau=inf (baseline for modularity eval)
    Timer t_build_inf;
    VIG vig_inf;
    if (use_naive) {
        vig_inf = build_vig_naive(cnf, std::numeric_limits<unsigned>::max());
    } else {
        if (threads == 0) vig_inf = build_vig_optimized(cnf, std::numeric_limits<unsigned>::max(), maxbuf);
        else              vig_inf = build_vig_optimized(cnf, std::numeric_limits<unsigned>::max(), maxbuf, threads);
    }
    const double sec_build_inf = t_build_inf.sec();

    // Build VIG with user tau (for segmentation)
    Timer t_build_user;
    VIG vig_user;
    if (use_naive) {
        vig_user = build_vig_naive(cnf, tau_user);
    } else {
        if (threads == 0) vig_user = build_vig_optimized(cnf, tau_user, maxbuf);
        else              vig_user = build_vig_optimized(cnf, tau_user, maxbuf, threads);
    }
    const double sec_build_user = t_build_user.sec();

    // Status: one-time timing report for parse and VIG builds
    std::cout << "segmentation_eval: parse_sec=" << sec_parse
              << " build_inf_sec=" << sec_build_inf
              << " build_user_sec=" << sec_build_user << "\n";

    // Prepare once: copy of edges we can sort per run without touching original
    std::vector<Edge> edges_user = vig_user.edges; // will be sorted per run

    // Compute total combinations with conditional sweeping
    auto count_total = [&]() -> uint64_t {
        uint64_t cnt = 0;
        for (double k : k_values) {
            
            for (double sx : size_exps) {
                for (bool mg : mod_guards) {
                    const std::vector<double>& gamma_list =
                        mg ? gammas : std::vector<double>{ gammas.front() };
                    const std::vector<bool>& anneal_list =
                        mg ? anneals : std::vector<bool>{ anneals.front() };
                    const std::vector<double>& dq_tol_list =
                        mg ? dq_tols : std::vector<double>{ dq_tols.front() };
                    for (double gma : gamma_list) {
                        for (bool an : anneal_list) {
                            const std::vector<double>& vscale_list =
                                (mg && an) ? dq_vscales : std::vector<double>{ dq_vscales.front() };
                            for (double tol0 : dq_tol_list) {
                                for (double vs : vscale_list) {
                                    const std::vector<std::string> amb_list =
                                        mg ? ambs : std::vector<std::string>{ ambs.front() };
                                    for (const auto& amb : amb_list) {
                                        const bool is_margin = (to_lower(amb) == "margin");
                                        const std::vector<double> gmarg_list =
                                            (mg && is_margin) ? gate_margins : std::vector<double>{ gate_margins.front() };
                                        for (double gmarg : gmarg_list) {
                                            (void)k; (void)sx; (void)mg; (void)gma; (void)an; (void)tol0; (void)vs; (void)amb; (void)gmarg;
                                            ++cnt;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        return cnt;
    };
    const uint64_t total = count_total();

    CSVWriter csv(out_csv);
    if (!csv.is_open()) {
        std::cerr << "Failed to open output CSV: " << out_csv << "\n";
        return 3;
    }
    csv.header(
        "vars","edges_user","edges_inf","comps","k","tau_user",
        "seg_sec",
        "impl","threads","agg_memory_inf","agg_memory_user",
        "keff","gini","pmax","entropyJ","modularity",
        "size_exp","modGuard","gamma","anneal",
        "dqTol0","dqVscale","amb","gateMargin","modGateAcc","modGateRej","modGateAmb"
    );

    std::cout << "segmentation_eval: writing " << total << " rows to " << out_csv << "\n";

    // Run segmentation for each combination without rebuilding VIG (conditional sweep)
    uint64_t written = 0;
    for (double k : k_values) {
        for (double sx : size_exps) {
            for (bool mg : mod_guards) {
                const std::vector<double>& gamma_list =
                    mg ? gammas : std::vector<double>{ gammas.front() };
                const std::vector<bool>& anneal_list =
                    mg ? anneals : std::vector<bool>{ anneals.front() };
                const std::vector<double>& dq_tol_list =
                    mg ? dq_tols : std::vector<double>{ dq_tols.front() };
                for (double gma : gamma_list) {
                    for (bool an : anneal_list) {
                        const std::vector<double>& vscale_list =
                            (mg && an) ? dq_vscales : std::vector<double>{ dq_vscales.front() };
                        for (double tol0 : dq_tol_list) {
                            for (double vs : vscale_list) {
                                const std::vector<std::string> amb_list =
                                    mg ? ambs : std::vector<std::string>{ ambs.front() };
                                for (const auto& amb : amb_list) {
                                    const bool is_margin = (to_lower(amb) == "margin");
                                    const std::vector<double> gmarg_list =
                                        (mg && is_margin) ? gate_margins : std::vector<double>{ gate_margins.front() };
                                    for (double gmarg : gmarg_list) {
                                        GraphSegmenterFH seg(nvars, k);
                                        GraphSegmenterFH::Config cfg = seg.config();
                                        cfg.sizeExponent = sx;
                                        cfg.use_modularity_guard = mg;
                                        cfg.gamma = gma;
                                        cfg.anneal_modularity_guard = an;
                                        cfg.dq_tolerance0 = tol0;
                                        cfg.dq_vscale = vs;
                                        std::string pol = amb; std::string pl = pol;
                                        std::transform(pl.begin(), pl.end(), pl.begin(), [](unsigned char c){ return std::tolower(c); });
                                        if (pl == "accept") cfg.ambiguous_policy = GraphSegmenterFH::Config::Ambiguous::Accept;
                                        else if (pl == "reject") cfg.ambiguous_policy = GraphSegmenterFH::Config::Ambiguous::Reject;
                                        else cfg.ambiguous_policy = GraphSegmenterFH::Config::Ambiguous::GateMargin;
                                        cfg.gate_margin_ratio = gmarg;
                                        seg.set_config(cfg);

                                        std::vector<Edge> edges = edges_user; // copy then sort
                                        Timer t_seg;
                                        seg.run(edges);
                                        const double sec_seg = t_seg.sec();

                                        auto comm_of = [&seg](uint32_t v) { return static_cast<int>(seg.component_no_compress(v)); };
                                        const double Q = modularity(nvars, vig_inf.edges, comm_of, /*gamma*/1.0);

                                        const auto sizes = component_sizes(nvars, [&seg](uint32_t v){ return seg.component_no_compress(v); });
                                        const auto cs = summarize_components(sizes);

                                        const double sec_total = t_total.sec();

                                        const std::string amb_out = mg ? (
                                            cfg.ambiguous_policy == GraphSegmenterFH::Config::Ambiguous::Accept ? "accept" :
                                            (cfg.ambiguous_policy == GraphSegmenterFH::Config::Ambiguous::Reject ? "reject" : "margin")
                                        ) : "n/a";
                                        const double gmarg_out = (mg && cfg.ambiguous_policy == GraphSegmenterFH::Config::Ambiguous::GateMargin) ? gmarg : -1.0;

                                        csv.row(
                                            nvars,
                                            static_cast<uint64_t>(vig_user.edges.size()),
                                            static_cast<uint64_t>(vig_inf.edges.size()),
                                            static_cast<uint64_t>(seg.num_components()),
                                            k,
                                            (tau_user == std::numeric_limits<unsigned>::max() ? -1 : static_cast<int>(tau_user)),
                                            sec_seg,
                                            (use_naive ? "naive" : "opt"),
                                            (use_naive ? 1 : (threads == 0 ? -1 : (int)threads)),
                                            static_cast<uint64_t>(vig_inf.aggregation_memory),
                                            static_cast<uint64_t>(vig_user.aggregation_memory),
                                            cs.keff, cs.gini, cs.pmax, cs.entropyJ, Q,
                                            sx, (mg ? 1 : 0), gma, (an ? 1 : 0),
                                            tol0, vs,
                                            amb_out,
                                            gmarg_out,
                                            seg.mod_guard_lb_accepts(), seg.mod_guard_ub_rejects(), seg.mod_guard_ambiguous()
                                        );
                                        ++written;
                                        if (total > 0 && (written % 1000 == 0)) {
                                            std::cout << "progress: " << written << "/" << total << " rows written\n";
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    std::cout << "segmentation_eval: done (" << written << " rows) -> " << out_csv << "\n";

    return 0;
}
