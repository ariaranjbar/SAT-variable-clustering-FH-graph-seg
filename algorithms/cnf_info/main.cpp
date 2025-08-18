#include <iostream>
#include <string>
#include "thesis/cnf.hpp"

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: cnf_info <file.cnf|-> [no-compact]" << std::endl;
        return 1;
    }
    std::string path = argv[1];
    bool compact = true;
    if (argc >= 3 && std::string(argv[2]) == "no-compact") compact = false;

    thesis::CNF cnf = (path == "-") ? thesis::CNF(std::cin, compact)
                                     : thesis::CNF(path, compact);
    if (!cnf.is_valid()) {
        std::cerr << "Invalid CNF or mismatch with declared clause count." << std::endl;
        return 2;
    }

    std::cout << "variables=" << cnf.get_variable_count()
              << ", clauses=" << cnf.get_clause_count() << std::endl;

    // Show first few clauses as a preview
    const auto& cls = cnf.get_clauses();
    size_t show = std::min<size_t>(cls.size(), 5);
    for (size_t i = 0; i < show; ++i) {
        std::cout << i << ":";
        for (int lit : cls[i]) std::cout << ' ' << lit;
        std::cout << " 0" << std::endl;
    }
    return 0;
}
