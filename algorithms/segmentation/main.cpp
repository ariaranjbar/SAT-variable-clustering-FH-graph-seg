#include <iostream>
#include <string>
#include "thesis/cli.hpp"
#include "thesis/cnf.hpp"
#include "thesis/vig.hpp"
#include "thesis/segmentation.hpp"
#include "thesis/timer.hpp"

int main(int argc, char** argv) {
    using namespace thesis;

    ArgParser cli("Segment the variable interaction graph (VIG) of a CNF.");
    cli.add_option(OptionSpec{.longName = "input", .shortName = 'i', .type = ArgType::String, .valueName = "FILE|-", .help = "Path to DIMACS CNF or '-' for stdin", .required = true});
    cli.add_option(OptionSpec{.longName = "tau", .shortName = '\0', .type = ArgType::UInt64, .valueName = "N|inf", .help = "Clause size threshold for VIG; use 'inf' for no limit", .required = false, .defaultValue = "inf", .allowInfToken = true});
    cli.add_option(OptionSpec{.longName = "k", .shortName = '\0', .type = ArgType::String, .valueName = "K", .help = "Segmentation parameter k (double)", .required = false, .defaultValue = "50.0"});
    cli.add_option(OptionSpec{.longName = "maxbuf", .shortName = '\0', .type = ArgType::Size, .valueName = "M", .help = "VIG optimized builder max contributions buffer", .required = false, .defaultValue = "50000000"});
    cli.add_option(OptionSpec{.longName = "threads", .shortName = 't', .type = ArgType::UInt64, .valueName = "K", .help = "Threads for optimized VIG build (0=auto)", .required = false, .defaultValue = "0"});
    cli.add_flag("naive", '\0', "Use naive VIG builder");
    cli.add_flag("opt", '\0', "Use optimized VIG builder (default)");

    bool proceed = true;
    try {
        proceed = cli.parse(argc, argv);
    } catch (const std::exception& e) {
        std::cerr << cli.usage(argv[0]) << "\n" << e.what() << "\n";
        return 1;
    }
    if (!proceed) { std::cout << cli.help(argv[0]); return 0; }

    const std::string path = cli.get_string("input");
    const unsigned tau = static_cast<unsigned>(cli.get_uint64("tau"));
    const std::size_t maxbuf = cli.get_size("maxbuf");
    const unsigned threads = static_cast<unsigned>(cli.get_uint64("threads"));
    const bool use_naive = cli.get_flag("naive");
    bool use_opt = cli.get_flag("opt");
    if (!use_naive && !use_opt) use_opt = true;

    double k = 50.0;
    try {
        k = std::stod(cli.get_string("k"));
    } catch (...) {
        std::cerr << "Invalid k value" << std::endl;
        return 1;
    }

    Timer t_total; // start total before parsing
    Timer t_parse;
    CNF cnf = (path == "-") ? CNF(std::cin, /*variable_compaction=*/true)
                              : CNF(path, /*variable_compaction=*/true);
    const double sec_parse = t_parse.sec();
    if (!cnf.is_valid()) { std::cerr << "Failed to parse CNF: " << path << "\n"; return 2; }

    Timer t_build;
    VIG g;
    if (use_naive) {
        g = build_vig_naive(cnf, tau);
    } else {
        if (threads == 0) g = build_vig_optimized(cnf, tau, maxbuf);
        else g = build_vig_optimized(cnf, tau, maxbuf, threads);
    }
    const double sec_build = t_build.sec();

    // Convert VIG edges to segmentation edges
    std::vector<SegEdge> sedges;
    sedges.reserve(g.edges.size());
    for (const auto& e : g.edges) {
        sedges.push_back(SegEdge{e.u, e.v, e.w});
    }

    Timer t_seg;
    GraphSegmenterFH seg(g.n, k);
    seg.run(sedges);
    const double sec_seg = t_seg.sec();
    const double sec_total = t_total.sec();

    std::cout << "vars=" << g.n
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
              << "\n";
    return 0;
}
