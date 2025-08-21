#include <iostream>
#include <string>
#include "thesis/cli.hpp"
#include "thesis/cnf.hpp"
#include "thesis/timer.hpp"

int main(int argc, char** argv) {
    using namespace thesis;

    std::string path;
    bool compact = true;

    // If first arg looks like an option, use ArgParser; otherwise, keep legacy positional behavior.
    bool use_options = (argc <= 1) || (argc > 1 && argv[1][0] == '-');
    if (use_options) {
        ArgParser cli("Show basic info about a DIMACS CNF file");
        cli.add_option(OptionSpec{.longName = "input", .shortName = 'i', .type = ArgType::String, .valueName = "FILE|-", .help = "Path to CNF file or '-' for stdin", .required = true});
        cli.add_flag("no-compact", '\0', "Disable variable compaction during parsing");

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
    thesis::CNF cnf = (path == "-") ? thesis::CNF(std::cin, compact)
                                     : thesis::CNF(path, compact);
    const double sec_parse = t_parse.sec();
    if (!cnf.is_valid()) {
        std::cerr << "Invalid CNF or mismatch with declared clause count." << std::endl;
        return 2;
    }

    std::cout << "variables=" << cnf.get_variable_count()
              << ", clauses=" << cnf.get_clause_count() << std::endl;

    // Show first few clauses as a preview
    const auto& cls = cnf.get_clauses();
    size_t show = std::min<size_t>(cls.size(), 5);
    for (size_t i = 0; i < show; i++) {
        std::cout << i << ":";
        for (int lit : cls[i]) std::cout << ' ' << lit;
        std::cout << " 0" << std::endl;
    }
    const double sec_total = t_total.sec();
    std::cout << "parse_sec=" << sec_parse << " total_sec=" << sec_total << std::endl;
    return 0;
}
