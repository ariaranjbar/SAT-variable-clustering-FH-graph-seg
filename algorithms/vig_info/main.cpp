#include <iostream>
#include <string>
#include <limits>
#include <chrono>
#include "thesis/cnf.hpp"
#include "thesis/vig.hpp"

int main(int argc, char** argv) {
    using namespace thesis;
    std::string path;
    unsigned tau = std::numeric_limits<unsigned>::max();
    size_t maxbuf = 50'000'000; // default max contributions in optimized mode
    bool use_naive = false, use_opt = true;
    unsigned threads = 0; // 0 means auto

    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if ((a == "-i" || a == "--input") && i + 1 < argc) { path = argv[++i]; }
        else if (a == "-tau" && i + 1 < argc) {
            std::string s = argv[++i];
            if (s == "inf" || s == "INF") tau = std::numeric_limits<unsigned>::max();
            else tau = static_cast<unsigned>(std::stoul(s));
        }
        else if (a == "-maxbuf" && i + 1 < argc) {
            maxbuf = static_cast<size_t>(std::stoull(argv[++i]));
        }
        else if (a == "--naive") { use_naive = true; use_opt = false; }
        else if (a == "--opt")   { use_opt = true;  use_naive = false; }
        else if ((a == "-t" || a == "--threads") && i + 1 < argc) {
            threads = static_cast<unsigned>(std::stoul(argv[++i]));
        }
    }

        if (path.empty()) {
        std::cerr << "Usage: " << argv[0]
                  << " -i file.cnf [-tau N|inf] [-maxbuf M] [--naive|--opt] [-t|--threads K]\n";
        return 1;
    }

        CNF cnf = (path == "-") ? CNF(std::cin, /*variable_compaction=*/true)
                                                         : CNF(path, /*variable_compaction=*/true);
    if (!cnf.is_valid()) {
        std::cerr << "Failed to parse CNF: " << path << "\n";
        return 2;
    }

    auto t0 = std::chrono::steady_clock::now();
    VIG g;
    if (use_naive) {
        g = build_vig_naive(cnf, tau, /*sort_desc=*/true);
    } else {
        if (threads == 0) {
            g = build_vig_optimized(cnf, tau, maxbuf, /*sort_desc=*/true);
        } else {
            g = build_vig_optimized(cnf, tau, maxbuf, /*sort_desc=*/true, threads);
        }
    }
    auto t1 = std::chrono::steady_clock::now();
    double sec = std::chrono::duration<double>(t1 - t0).count();

    std::cout << "vars=" << g.n
                        << " edges=" << g.edges.size()
                        << " time_sec=" << sec
                        << " impl=" << (use_naive ? "naive" : "opt")
                        << " tau=" << (tau == std::numeric_limits<unsigned>::max() ? -1 : (int)tau)
                        << " threads=" << (use_naive ? 1 : (threads == 0 ? -1 : (int)threads))
                        << " agg_memory=" << g.aggregation_memory
                        << "\n";
    return 0;
}
