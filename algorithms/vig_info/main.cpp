#include <iostream>
#include <string>
#include <limits>
#include "thesis/timer.hpp"
#include "thesis/cli.hpp"
#include "thesis/cnf.hpp"
#include "thesis/vig.hpp"

int main(int argc, char** argv) {
    using namespace thesis;
    ArgParser cli("Compute variable-interaction graph statistics for a CNF file");
    cli.add_option(OptionSpec{.longName = "input", .shortName = 'i', .type = ArgType::String, .valueName = "FILE", .help = "Path to DIMACS CNF file, or '-' for stdin", .required = true});
    cli.add_option(OptionSpec{.longName = "tau", .shortName = '\0', .type = ArgType::UInt64, .valueName = "N|inf", .help = "Clause size threshold; use 'inf' for no limit", .required = false, .defaultValue = "inf", .allowInfToken = true});
    cli.add_option(OptionSpec{.longName = "maxbuf", .shortName = '\0', .type = ArgType::Size, .valueName = "M", .help = "Max contributions buffer in optimized mode", .required = false, .defaultValue = "50000000"});
    cli.add_option(OptionSpec{.longName = "threads", .shortName = 't', .type = ArgType::UInt64, .valueName = "K", .help = "Number of worker threads (0=auto)", .required = false, .defaultValue = "0"});
    cli.add_flag("naive", '\0', "Use naive implementation");
    cli.add_flag("opt", '\0', "Use optimized implementation");

    bool proceed = true;
    try {
        proceed = cli.parse(argc, argv);
    } catch (const std::exception& e) {
        std::cerr << cli.usage(argv[0]) << "\n" << e.what() << "\n";
        return 1;
    }
    if (!proceed) {
        std::cout << cli.help(argv[0]);
        return 0;
    }

    std::string path = cli.get_string("input");
    unsigned tau = static_cast<unsigned>(cli.get_uint64("tau"));
    size_t maxbuf = cli.get_size("maxbuf");
    unsigned threads = static_cast<unsigned>(cli.get_uint64("threads"));
    bool use_naive = cli.get_flag("naive");
    bool use_opt = cli.get_flag("opt");
    if (!use_naive && !use_opt) use_opt = true; // default

    Timer t_total; // start total before parsing
    Timer t_parse;
    CNF cnf = (path == "-") ? CNF(std::cin, /*variable_compaction=*/true)
                             : CNF(path, /*variable_compaction=*/true);
    const double sec_parse = t_parse.sec();
    if (!cnf.is_valid()) {
        std::cerr << "Failed to parse CNF: " << path << "\n";
        return 2;
    }

    Timer t_build;
    VIG g;
    if (use_naive) {
        g = build_vig_naive(cnf, tau);
    } else {
        if (threads == 0) {
            g = build_vig_optimized(cnf, tau, maxbuf);
        } else {
            g = build_vig_optimized(cnf, tau, maxbuf, threads);
        }
    }
    const double sec_build = t_build.sec();
    const double sec_total = t_total.sec();

    std::cout << "vars=" << g.n
                        << " edges=" << g.edges.size()
                        << " parse_sec=" << sec_parse
                        << " vig_build_sec=" << sec_build
                        << " total_sec=" << sec_total
                        << " impl=" << (use_naive ? "naive" : "opt")
                        << " tau=" << (tau == std::numeric_limits<unsigned>::max() ? -1 : (int)tau)
                        << " threads=" << (use_naive ? 1 : (threads == 0 ? -1 : (int)threads))
                        << " agg_memory=" << g.aggregation_memory
                        << "\n";
    return 0;
}
