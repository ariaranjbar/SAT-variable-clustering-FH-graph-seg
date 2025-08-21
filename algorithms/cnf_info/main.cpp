#include <iostream>
#include <string>
#include "thesis/cli.hpp"
#include "thesis/cnf.hpp"
#include "thesis/timer.hpp"

int main(int argc, char** argv) {
    using namespace thesis;

    std::string path;
    bool compact = true;
    bool normalize = true;

    // If first arg looks like an option, use ArgParser; otherwise, keep legacy positional behavior.
    bool use_options = (argc <= 1) || (argc > 1 && argv[1][0] == '-');
    if (use_options) {
        ArgParser cli("Show basic info about a DIMACS CNF file");
        cli.add_option(OptionSpec{.longName = "input", .shortName = 'i', .type = ArgType::String, .valueName = "FILE|-", .help = "Path to CNF file or '-' for stdin", .required = true});
        cli.add_flag("no-compact", '\0', "Disable variable compaction during parsing");
        cli.add_flag("no-normalize", '\0', "Disable clause normalization during parsing");

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

        path = cli.get_string("input");
        compact = !cli.get_flag("no-compact");
        normalize = !cli.get_flag("no-normalize");
    } else {
        // Legacy: cnf_info <file.cnf|-> [no-compact]
        if (argc < 2) {
            std::cerr << "Usage: cnf_info <file.cnf|-> [no-compact]" << std::endl;
            return 1;
        }
        path = argv[1];
        if (argc >= 3 && std::string(argv[2]) == "no-compact") compact = false;
    }

    thesis::Timer t_total;
    thesis::Timer t_parse;
    thesis::CNF cnf = (path == "-") ? thesis::CNF(std::cin, compact, normalize)
                                     : thesis::CNF(path, compact, normalize);
    const double sec_parse = t_parse.sec();
    if (!cnf.is_valid()) {
        std::cerr << "Invalid CNF or mismatch with declared clause count." << std::endl;
        return 2;
    }

    const double sec_total = t_total.sec();
    std::cout << "vars=" << cnf.get_variable_count()
              << " clauses=" << cnf.get_clause_count()
              << " parse_sec=" << sec_parse
              << " total_sec=" << sec_total
              << " compacted=" << (compact ? 1 : 0)
              << " normalized=" << (normalize ? 1 : 0)
              << "\n";
    return 0;
}
