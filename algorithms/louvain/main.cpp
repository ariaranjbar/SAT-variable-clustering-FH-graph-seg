#include <iostream>
#include <string>
#include <limits>
#include <algorithm>
#include <filesystem>

#include "thesis/cli.hpp"
#include "thesis/cnf.hpp"
#include "thesis/vig.hpp"
#include "thesis/community.h"
#include "thesis/timer.hpp"
#include "thesis/csv.hpp"

int main(int argc, char** argv) {
    using namespace thesis;

    ArgParser cli("Compute Louvain community structure on the VIG of a CNF");
    cli.add_option(OptionSpec{.longName = "input", .shortName = 'i', .type = ArgType::String, .valueName = "FILE|-", .help = "Path to DIMACS CNF or '-' for stdin", .required = true});
    cli.add_option(OptionSpec{.longName = "tau", .shortName = '\0', .type = ArgType::UInt64, .valueName = "N|inf", .help = "Clause size threshold for VIG; use 'inf' for no limit", .required = false, .defaultValue = "inf", .allowInfToken = true});
    cli.add_option(OptionSpec{.longName = "nb-pass", .shortName = '\0', .type = ArgType::Int64, .valueName = "N", .help = "Max passes per Louvain level (-1 = until converge)", .required = false, .defaultValue = "-1"});
    cli.add_option(OptionSpec{.longName = "min-mod", .shortName = '\0', .type = ArgType::String, .valueName = "EPS", .help = "Minimum modularity improvement threshold per pass", .required = false, .defaultValue = "1e-7"});
    cli.add_option(OptionSpec{.longName = "graph-out", .shortName = '\0', .type = ArgType::String, .valueName = "BASE", .help = "Write Louvain graph CSVs to BASE.node.csv and BASE.edges.csv", .required = false, .defaultValue = ""});

    bool proceed = true;
    try { proceed = cli.parse(argc, argv); } catch (const std::exception& e) {
        std::cerr << cli.usage(argv[0]) << "\n" << e.what() << "\n";
        return 1;
    }
    if (!proceed) { std::cout << cli.help(argv[0]); return 0; }

    const std::string path = cli.get_string("input");
    const unsigned tau = static_cast<unsigned>(cli.get_uint64("tau"));
    // No VIG builder selection here; Louvain graph is built directly from CNF.

    long long nb_pass_ll = cli.get_int64("nb-pass");
    if (nb_pass_ll < -1) nb_pass_ll = -1; // sanitize
    int nb_pass = static_cast<int>(nb_pass_ll);

    double min_mod = 1e-7;
    try { min_mod = std::stod(cli.get_string("min-mod")); } catch (...) { /* keep default */ }

    Timer t_total;
    Timer t_parse;
    CNF cnf = (path == "-") ? CNF(std::cin, /*variable_compaction=*/true)
                              : CNF(path, /*variable_compaction=*/true);
    const double sec_parse = t_parse.sec();
    if (!cnf.is_valid()) { std::cerr << "Failed to parse CNF: " << path << "\n"; return 2; }

    // Build Louvain graph directly from CNF
    Timer t_graph;
    Louvain::Graph lg = Louvain::build_graph(cnf, tau);
    const double sec_graph = t_graph.sec();

    // Run Louvain passes until no improvement at current level
    Timer t_louvain;
    Community comm(lg, nb_pass, min_mod);
    double mod0 = comm.modularity();
    bool improved = comm.one_level();
    double mod1 = comm.modularity();
    const double sec_louvain = t_louvain.sec();
    const double sec_total = t_total.sec();

    // Compute number of communities (unique labels in n2c)
    int comps = 0;
    {
        std::vector<char> seen(static_cast<size_t>(comm.size), 0);
        for (int v = 0; v < comm.size; ++v) {
            int c = comm.n2c[v];
            if (c >= 0 && !seen[static_cast<size_t>(c)]) { seen[static_cast<size_t>(c)] = 1; ++comps; }
        }
    }

    // Optional outputs
    if (cli.provided("graph-out")) {
        const std::string base = cli.get_string("graph-out");
        if (base.empty()) { std::cerr << "--graph-out requires a base path\n"; return 3; }
        const std::string nodes_path = base + ".node.csv";
        const std::string edges_path = base + ".edges.csv";
        CSVWriter ncsv(nodes_path);
        if (!ncsv.is_open()) { std::cerr << "Failed to open nodes output file: " << nodes_path << "\n"; return 3; }
        CSVWriter ecsv(edges_path);
        if (!ecsv.is_open()) { std::cerr << "Failed to open edges output file: " << edges_path << "\n"; return 3; }
        // Nodes: id,component
        ncsv.header("id", "component");
        for (int v = 0; v < comm.size; ++v) {
            int c = comm.n2c[v];
            ncsv.row(v, c);
        }
        // Edges: undirected unique pairs u<v with weight
        ecsv.header("u","v","w");
        for (unsigned int u = 0; u < lg.nb_nodes; ++u) {
            auto p = lg.neighbors(u);
            unsigned int deg = lg.nb_neighbors(u);
            for (unsigned int i = 0; i < deg; ++i) {
                unsigned int v = *(p.first + i);
                float w = (lg.weights.size() == 0) ? 1.f : *(p.second + i);
                if (u < v) ecsv.row(u, v, static_cast<double>(w));
            }
        }
    }

    std::cout << "vars=" << cnf.get_variable_count()
              << " parse_sec=" << sec_parse
              << " louvain_graph_sec=" << sec_graph
              << " louvain_sec=" << sec_louvain
              << " total_sec=" << sec_total
              << " tau=" << (tau == std::numeric_limits<unsigned>::max() ? -1 : (int)tau)
              << " mod0=" << mod0
              << " mod1=" << mod1
              << " comps=" << comps
              << " improved=" << (improved ? 1 : 0)
              << "\n";

    return 0;
}
