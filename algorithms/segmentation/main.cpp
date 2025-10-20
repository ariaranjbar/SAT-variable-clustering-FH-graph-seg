#include <iostream>
#include <string>
#include <filesystem>
#include <vector>
#include <limits>
#include <algorithm>
#include "thesis/cli.hpp"
#include "thesis/cnf.hpp"
#include "thesis/vig.hpp"
#include "thesis/segmentation.hpp"
#include "thesis/timer.hpp"
#include "thesis/csv.hpp"
#include "thesis/comp_metrics.hpp"
#include "thesis/modularity.hpp"

int main(int argc, char **argv)
{
    using namespace thesis;

    ArgParser cli("Segment the variable interaction graph (VIG) of a CNF.");
    cli.add_option(OptionSpec{.longName = "input", .shortName = 'i', .type = ArgType::String, .valueName = "FILE|-", .help = "Path to DIMACS CNF or '-' for stdin", .required = true});
    cli.add_option(OptionSpec{.longName = "tau", .shortName = '\0', .type = ArgType::UInt64, .valueName = "N|inf", .help = "Clause size threshold for VIG; use 'inf' for no limit", .required = false, .defaultValue = "inf", .allowInfToken = true});
    cli.add_option(OptionSpec{.longName = "k", .shortName = 'k', .type = ArgType::String, .valueName = "K", .help = "Segmentation parameter k (double)", .required = false, .defaultValue = std::to_string(GraphSegmenterFH::kDefaultK)});
    cli.add_option(OptionSpec{.longName = "maxbuf", .shortName = '\0', .type = ArgType::Size, .valueName = "BYTES", .help = "VIG optimized builder max contributions buffer", .required = false, .defaultValue = "50000000"});
    cli.add_option(OptionSpec{.longName = "threads", .shortName = 't', .type = ArgType::UInt64, .valueName = "N", .help = "Threads for optimized VIG build (0=auto)", .required = false, .defaultValue = "0"});
    cli.add_option(OptionSpec{.longName = "comp-out", .shortName = '\0', .type = ArgType::String, .valueName = "DIR", .help = "Optional dir to write components CSV (auto-named: <cnf>_components.csv)", .required = false, .defaultValue = ""});
    // Deprecated: comp-base (kept for compatibility). Prefer --output-base.
    cli.add_option(OptionSpec{.longName = "comp-base", .shortName = '\0', .type = ArgType::String, .valueName = "NAME", .help = "[deprecated] Base name for components file (use --output-base instead)", .required = false, .defaultValue = ""});
    cli.add_option(OptionSpec{.longName = "output-base", .shortName = '\0', .type = ArgType::String, .valueName = "NAME", .help = "Optional base name for outputs (used by --comp-out, --graph-out, --cross-out)", .required = false, .defaultValue = ""});
    cli.add_flag("naive", '\0', "Use naive VIG builder");
    cli.add_flag("opt", '\0', "Use optimized VIG builder (default)");
    cli.add_option(OptionSpec{.longName = "graph-out", .shortName = '\0', .type = ArgType::String, .valueName = "DIR", .help = "Write graph CSVs into DIR as <base>.node.csv and <base>.edges.csv", .required = false, .defaultValue = ""});
    cli.add_option(OptionSpec{.longName = "cross-out", .shortName = '\0', .type = ArgType::String, .valueName = "DIR", .help = "Write strongest cross-component edges CSV into DIR as <base>_cross.csv (columns: u,v,w)", .required = false, .defaultValue = ""});
    // Segmentation behavior knobs
    cli.add_option(OptionSpec{.longName = "size-exp", .shortName = '\0', .type = ArgType::String, .valueName = "X", .help = "Exponent for |C| in gate denominator (1.0 => k/|C|)", .required = false, .defaultValue = std::to_string(GraphSegmenterFH::Config::kDefaultSizeExponent)});
    // Modularity guard knobs
    cli.add_flag("no-mod-guard", '\0', "Disable modularity guard (ΔQ tests)");
    cli.add_option(OptionSpec{.longName = "gamma", .shortName = '\0', .type = ArgType::String, .valueName = "G", .help = "Modularity resolution gamma", .required = false, .defaultValue = std::to_string(GraphSegmenterFH::Config::kDefaultGamma)});
    cli.add_flag("no-anneal-guard", '\0', "Disable annealing of ΔQ tolerance (use fixed 0)");
    {
        std::ostringstream ossTol; ossTol << GraphSegmenterFH::Config::kDefaultDqTolerance0;
        cli.add_option(OptionSpec{.longName = "dq-tol0", .shortName = '\0', .type = ArgType::String, .valueName = "T", .help = "Initial ΔQ tolerance (e.g., 1e-3)", .required = false, .defaultValue = ossTol.str()});
    }
    cli.add_option(OptionSpec{.longName = "dq-vscale", .shortName = '\0', .type = ArgType::String, .valueName = "S", .help = "Scale for tolerance annealing; 0 => auto (~mean degree)", .required = false, .defaultValue = std::to_string(GraphSegmenterFH::Config::kDefaultDqVscale)});
    {
        std::string ambDef = (GraphSegmenterFH::Config::kDefaultAmbiguousPolicy == GraphSegmenterFH::Config::Ambiguous::Accept) ? "accept" : (GraphSegmenterFH::Config::kDefaultAmbiguousPolicy == GraphSegmenterFH::Config::Ambiguous::Reject ? "reject" : "margin");
        cli.add_option(OptionSpec{.longName = "ambiguous", .shortName = '\0', .type = ArgType::String, .valueName = "POLICY", .help = "Ambiguous policy: accept|reject|margin", .required = false, .defaultValue = ambDef});
    }
    {
        std::ostringstream ossGM; ossGM << GraphSegmenterFH::Config::kDefaultGateMarginRatio;
        cli.add_option(OptionSpec{.longName = "gate-margin", .shortName = '\0', .type = ArgType::String, .valueName = "RATIO", .help = "Gate margin ratio for 'margin' policy (e.g., 0.05)", .required = false, .defaultValue = ossGM.str()});
    }

    bool proceed = true;
    try
    {
        proceed = cli.parse(argc, argv);
    }
    catch (const std::exception &e)
    {
        std::cerr << cli.usage(argv[0]) << "\n"
                  << e.what() << "\n";
        return 1;
    }
    if (!proceed)
    {
        std::cout << cli.help(argv[0]);
        return 0;
    }

    const std::string path = cli.get_string("input");
    const unsigned tau = static_cast<unsigned>(cli.get_uint64("tau"));
    const std::size_t maxbuf = cli.get_size("maxbuf");
    const unsigned threads = static_cast<unsigned>(cli.get_uint64("threads"));
    const bool use_naive = cli.get_flag("naive");
    bool use_opt = cli.get_flag("opt");
    if (!use_naive && !use_opt)
        use_opt = true;

    double k = GraphSegmenterFH::kDefaultK;
    try
    {
        k = std::stod(cli.get_string("k"));
    }
    catch (...)
    {
        std::cerr << "Invalid k value" << std::endl;
        return 1;
    }

    Timer t_total; // start total before parsing
    Timer t_parse;
    CNF cnf = (path == "-") ? CNF(std::cin, /*variable_compaction=*/true)
                            : CNF(path, /*variable_compaction=*/true);
    const double sec_parse = t_parse.sec();
    if (!cnf.is_valid())
    {
        std::cerr << "Failed to parse CNF: " << path << "\n";
        return 2;
    }

    Timer t_build;
    VIG g;
    if (use_naive)
    {
        g = build_vig_naive(cnf, tau);
    }
    else
    {
        if (threads == 0)
            g = build_vig_optimized(cnf, tau, maxbuf);
        else
            g = build_vig_optimized(cnf, tau, maxbuf, threads);
    }
    const double sec_build = t_build.sec();

    Timer t_seg;
    GraphSegmenterFH seg(g.n, k);
    // Apply optional config knobs
    {
        GraphSegmenterFH::Config cfg = seg.config();
        try {
            cfg.sizeExponent = std::stod(cli.get_string("size-exp"));
        } catch (...) {
            std::cerr << "Invalid size-exp value" << std::endl;
            return 1;
        }
        if (cli.get_flag("no-mod-guard")) cfg.use_modularity_guard = false;
        try {
            cfg.gamma = std::stod(cli.get_string("gamma"));
        } catch (...) {
            std::cerr << "Invalid gamma value" << std::endl;
            return 1;
        }
        if (cli.get_flag("no-anneal-guard")) cfg.anneal_modularity_guard = false;
        try {
            cfg.dq_tolerance0 = std::stod(cli.get_string("dq-tol0"));
        } catch (...) {
            std::cerr << "Invalid dq-tol0 value" << std::endl;
            return 1;
        }
        try {
            cfg.dq_vscale = std::stod(cli.get_string("dq-vscale"));
        } catch (...) {
            std::cerr << "Invalid dq-vscale value" << std::endl;
            return 1;
        }
        // ambiguous policy
        {
            std::string pol = cli.get_string("ambiguous");
            std::transform(pol.begin(), pol.end(), pol.begin(), [](unsigned char c){ return std::tolower(c); });
            if (pol == "accept") cfg.ambiguous_policy = GraphSegmenterFH::Config::Ambiguous::Accept;
            else if (pol == "reject") cfg.ambiguous_policy = GraphSegmenterFH::Config::Ambiguous::Reject;
            else if (pol == "margin" || pol == "gatemargin") cfg.ambiguous_policy = GraphSegmenterFH::Config::Ambiguous::GateMargin;
            else {
                std::cerr << "Invalid ambiguous policy (use accept|reject|margin)" << std::endl;
                return 1;
            }
        }
        try {
            cfg.gate_margin_ratio = std::stod(cli.get_string("gate-margin"));
        } catch (...) {
            std::cerr << "Invalid gate-margin value" << std::endl;
            return 1;
        }
        seg.set_config(cfg);
    }
    seg.run(g.edges);
    const double sec_seg = t_seg.sec();
    const double sec_total = t_total.sec();

    // Compute modularity of the segmentation (resolution gamma=1.0)
    double Q = modularity(
        static_cast<uint32_t>(g.n),
        g.edges,
        [&](uint32_t v)
        { return seg.component_no_compress(v); },
        1.0);

    // Compute metrics once
    auto sizes = thesis::component_sizes(static_cast<uint32_t>(g.n), [&](uint32_t v)
                                         { return seg.component_no_compress(v); });
    thesis::CompSummary cs = thesis::summarize_components(sizes);

    // Optional: write full graph (nodes with component labels, then edges) to files
    if (cli.provided("graph-out"))
    {
        const std::string graph_out_dir = cli.get_string("graph-out");
        if (graph_out_dir.empty())
        {
            std::cerr << "--graph-out requires a directory path\n";
            return 3;
        }
        std::error_code ec;
        std::filesystem::path gdir(graph_out_dir);
        if (!std::filesystem::exists(gdir, ec))
        {
            if (!std::filesystem::create_directories(gdir, ec))
            {
                std::cerr << "Failed to create output directory: " << graph_out_dir << "\n";
                return 3;
            }
        }
        else if (!std::filesystem::is_directory(gdir, ec))
        {
            std::cerr << "--graph-out path is not a directory: " << graph_out_dir << "\n";
            return 3;
        }
        std::string graph_base = cli.provided("output-base") ? cli.get_string("output-base") : std::string{};
        if (graph_base.empty())
        {
            if (path != "-")
            {
                std::filesystem::path p(path);
                p = p.filename();
                while (p.has_extension())
                    p = p.stem();
                graph_base = p.string();
                if (graph_base.empty())
                    graph_base = "cnf";
            }
            else
            {
                graph_base = "stdin";
            }
        }
        const std::string nodes_path = (gdir / (graph_base + ".node.csv")).string();
        const std::string edges_path = (gdir / (graph_base + ".edges.csv")).string();

        CSVWriter ncsv(nodes_path);
        if (!ncsv.is_open())
        {
            std::cerr << "Failed to open nodes output file: " << nodes_path << "\n";
            return 3;
        }
        CSVWriter ecsv(edges_path);
        if (!ecsv.is_open())
        {
            std::cerr << "Failed to open edges output file: " << edges_path << "\n";
            return 3;
        }

        // Nodes CSV: id,component
        ncsv.header("id", "component");
        for (unsigned v = 0; v < g.n; ++v)
        {
            unsigned r = seg.component_no_compress(v);
            ncsv.row(v, r);
        }

        // Edges CSV: u,v,w
        ecsv.header("u", "v", "w");
        for (const auto &e : g.edges)
        {
            ecsv.row(e.u, e.v, e.w);
        }
    }

    // Optional: write strongest cross-component edges to CSV
    if (cli.provided("cross-out"))
    {
        const std::string cross_out_dir = cli.get_string("cross-out");
        if (cross_out_dir.empty())
        {
            std::cerr << "--cross-out requires a directory path\n";
            return 3;
        }
        std::error_code ec;
        std::filesystem::path cdir(cross_out_dir);
        if (!std::filesystem::exists(cdir, ec))
        {
            if (!std::filesystem::create_directories(cdir, ec))
            {
                std::cerr << "Failed to create output directory: " << cross_out_dir << "\n";
                return 3;
            }
        }
        else if (!std::filesystem::is_directory(cdir, ec))
        {
            std::cerr << "--cross-out path is not a directory: " << cross_out_dir << "\n";
            return 3;
        }
        std::string base = cli.provided("output-base") ? cli.get_string("output-base") : std::string{};
        if (base.empty())
        {
            if (path != "-")
            {
                std::filesystem::path p(path);
                p = p.filename();
                while (p.has_extension())
                    p = p.stem();
                base = p.string();
                if (base.empty())
                    base = "cnf";
            }
            else
            {
                base = "stdin";
            }
        }
        const std::filesystem::path cross_file = cdir / (base + "_cross.csv");
        CSVWriter csv(cross_file.string());
        if (!csv.is_open())
        {
            std::cerr << "Failed to open cross-out file: " << cross_file.string() << "\n";
            return 3;
        }
        csv.header("u", "v", "w");
        auto strongest = seg.strongest_inter_component_edges();
        std::sort(strongest.begin(), strongest.end(), [](const SegEdge &a, const SegEdge &b)
                  { return a.w > b.w; });
        for (const auto &e : strongest)
            csv.row(e.u, e.v, e.w);
    }

    // Optional: write components CSV with size and minimum internal weight per component
    if (cli.provided("comp-out"))
    {
        const std::string comp_out_dir = cli.get_string("comp-out");
        std::error_code ec;
        std::filesystem::path outdir(comp_out_dir);
        if (comp_out_dir.empty())
        {
            std::cerr << "--comp-out requires a directory path\n";
            return 3;
        }
        if (!std::filesystem::exists(outdir, ec))
        {
            if (!std::filesystem::create_directories(outdir, ec))
            {
                std::cerr << "Failed to create output directory: " << comp_out_dir << "\n";
                return 3;
            }
        }
        else if (!std::filesystem::is_directory(outdir, ec))
        {
            std::cerr << "--comp-out path is not a directory: " << comp_out_dir << "\n";
            return 3;
        }

        // Derive base name from input CNF path unless overridden by --output-base (preferred) or --comp-base
        std::string base_name = cli.provided("output-base") ? cli.get_string("output-base")
                                                            : (cli.provided("comp-base") ? cli.get_string("comp-base") : std::string{});
        if (base_name.empty())
        {
            if (path != "-")
            {
                std::filesystem::path p(path);
                p = p.filename();
                while (p.has_extension())
                    p = p.stem();
                base_name = p.string();
                if (base_name.empty())
                    base_name = "cnf";
            }
            else
            {
                base_name = "stdin";
            }
        }
        const std::filesystem::path out_file = outdir / (base_name + "_components.csv");

        CSVWriter ofs(out_file.string());
        if (!ofs.is_open())
        {
            std::cerr << "Failed to open components output file: " << out_file.string() << "\n";
            return 3;
        }
        ofs.header("component_id", "size", "min_internal_weight");
        std::vector<char> seen(g.n, 0);
        std::vector<unsigned> reps;
        reps.reserve(seg.num_components());
        for (unsigned v = 0; v < g.n; ++v)
        {
            unsigned r = seg.component_no_compress(v);
            if (seen[r])
                continue;
            seen[r] = 1;
            reps.push_back(r);
        }
        std::sort(reps.begin(), reps.end(), [&](unsigned a, unsigned b)
                  { return seg.comp_size(a) > seg.comp_size(b); });
        for (unsigned r : reps)
        {
            ofs.row(r, seg.comp_size(r), seg.comp_min_weight(r));
        }
    }

    const auto cfg = seg.config();
    std::cout << "vars=" << g.n
              << " clauses=" << cnf.get_clause_count()
              << " edges=" << g.edges.size()
              << " comps=" << seg.num_components()
              << " k=" << k
              << " tau=" << (tau == std::numeric_limits<unsigned>::max() ? -1 : (int)tau)
              << " parse_sec=" << sec_parse
              << " vig_build_sec=" << sec_build
              << " seg_sec=" << sec_seg
              << " total_sec=" << sec_total
              << " impl=" << (use_naive ? "naive" : "opt")
              << " threads=" << (use_naive ? 1 : (threads == 0 ? -1 : (int)threads))
              << " agg_memory=" << g.aggregation_memory
              << " keff=" << cs.keff
              << " gini=" << cs.gini
              << " pmax=" << cs.pmax
              << " entropyJ=" << cs.entropyJ
              << " modularity=" << Q
              // Segmentation knobs summary for benchmarking
              << " size_exp=" << cfg.sizeExponent
              << " modGuard=" << (cfg.use_modularity_guard ? 1 : 0)
              << " gamma=" << cfg.gamma
              << " anneal=" << (cfg.anneal_modularity_guard ? 1 : 0)
              << " dqTol0=" << cfg.dq_tolerance0
              << " dqVscale=" << cfg.dq_vscale
              << " amb=" << (cfg.ambiguous_policy == GraphSegmenterFH::Config::Ambiguous::Accept ? "accept" : (cfg.ambiguous_policy == GraphSegmenterFH::Config::Ambiguous::Reject ? "reject" : "margin"))
              << " gateMargin=" << cfg.gate_margin_ratio
              << " modGateAcc=" << seg.mod_guard_lb_accepts()
              << " modGateRej=" << seg.mod_guard_ub_rejects()
              << " modGateAmb=" << seg.mod_guard_ambiguous()
              << "\n";
    return 0;
}
