// ----------------------------------------------------------------------------
// segmentation.cpp
//
// Felzenszwalb–Huttenlocher (FH) style graph segmentation with optional
// modularity guard.
//
// Implementation highlights (matches code below):
//  - Inputs: undirected similarity edges (u,v,w) with w>0; distance d=1/w.
//  - Preprocessing: edges sorted descending by weight (strongest first).
//  - FH predicate with tunable bias: each component C keeps max_dist(C)
//    (max edge distance seen within C so far). The gate is
//        Gate(C) = max_dist(C) + k / |C|^sizeExponent
//    A merge (a,b) is allowed if (1/w)/d_scale <= min(Gate(a), Gate(b)).
//  - Union-Find backbone: union-by-rank + path compression. On accept,
//    update comp_size, max_dist and (if enabled) modularity guard state.
//  - Modularity guard (optional): prevents merges that would clearly reduce
//    modularity at resolution gamma. Maintains for each component:
//      * comp_vol[r]: weighted degree (sum of incident w’s)
//      * lb_comp_internal_w[r]: lower bound of internal weight (sum of w’s of
//        edges observed intra-component so far)
//      * m = sum of all edge weights
//    Two quick tests around ΔQ for merging a,b:
//      * Lower-bound accept: ΔQ_min = (w_ab/m) - gamma*vol[a]*vol[b]/(2 m^2).
//        If ΔQ_min > tolerance, accept immediately.
//      * Upper-bound reject: bound best possible e_ab using cutA_ub, cutB_ub
//        from volumes and lb_internal; compute ΔQ_max and reject if
//        ΔQ_max < tolerance.
//    Ambiguous cases: configurable policy {Accept, Reject, GateMargin}.
//    Tolerance can be annealed: small negative allowed for tiny comps,
//    contracts toward 0 with component volume (scale ~ mean degree by default).
//  - Inter-component candidates: edges that failed merge are stored (in the
//    same descending order). strongest_inter_component_edges() returns at most
//    one strongest edge per unordered pair of final components (first seen wins
//    due to sort order).
//  - Complexity: one sort O(E log E) + near-linear passes with DSU operations.
//  - Determinism: order is driven by the sort and stable arithmetic; no threads.
//  - Memory: minimal extra state (DSU arrays, a few per-component vectors,
//    and the optional candidate list).
// ----------------------------------------------------------------------------

#include "thesis/segmentation.hpp"
#include <numeric>
#include <unordered_map>
#include <unordered_set>
#include <cstdlib>
#include <iostream>

namespace thesis
{

    GraphSegmenterFH::GraphSegmenterFH(unsigned n, double k) { reset(n, k); }

    void GraphSegmenterFH::reset(unsigned n, double k)
    {
        dsu_.reset(n);
        mod_guard_lb_accepts_ = 0;
        mod_guard_ub_rejects_ = 0;
        mod_guard_ambiguous_ = 0;
        comp_size_.assign(n, 1);
        if (cfg_.use_modularity_guard)
        {
            comp_vol_.assign(n, 0);
            lb_comp_internal_w_.assign(n, 0);
        }
        max_dist_.assign(n, 0);
        k_ = k;
        d_scale_ = 1.0;
        intercomp_candidates_.clear();
    }

    static inline bool edge_desc(const SegEdge &a, const SegEdge &b) { return a.w > b.w; }

    void GraphSegmenterFH::run(std::vector<SegEdge> &edges)
    {
        // Sort edges to process in order of weight
        std::sort(edges.begin(), edges.end(), edge_desc);

        // Create a copy of edges for neighbor tracking
        const size_t num_vars = dsu_.size();
        std::vector<unsigned> var_edge_counts(num_vars, 0);
        for (const auto &e : edges)
        {
            var_edge_counts[e.u]++;
            var_edge_counts[e.v]++;
        }
        for (unsigned i = 1; i < num_vars; i++)
        {
            var_edge_counts[i] += var_edge_counts[i - 1];
        }
        const size_t total_var_edges = var_edge_counts.back();
        std::vector<std::pair<unsigned, double>> var_neighbors(total_var_edges);
        for (const auto &e : edges)
        {
            var_neighbors[--var_edge_counts[e.u]] = std::make_pair(e.v, e.w);
            var_neighbors[--var_edge_counts[e.v]] = std::make_pair(e.u, e.w);
        }

        // function to get sum of weights of edges from u to component c
        auto sum_weights_to_comp = [&](unsigned u, unsigned c) {
            double sum = 0.0;
            unsigned start = var_edge_counts[u];
            unsigned end_idx = (u + 1 < num_vars ? var_edge_counts[u + 1] : total_var_edges);
            for (unsigned i = start; i < end_idx; ++i) {
                unsigned v = var_neighbors[i].first;
                double w = var_neighbors[i].second;
                if (dsu_.find(v) == c) {
                    sum += w;
                }
            }
            return sum;
        };

        //// function to get weight of edge from node a to node b (0 if none)
        // auto a_b_weight = [&](unsigned a, unsigned b) {
        //     unsigned start_a = var_edge_counts[a];
        //     unsigned end_a = (a + 1 < num_vars ? var_edge_counts[a + 1] : total_var_edges);
        //     unsigned start_b = var_edge_counts[b];
        //     unsigned end_b = (b + 1 < num_vars ? var_edge_counts[b + 1] : total_var_edges);
        //     unsigned second = b, start = start_a, end = end_a;
        //     if (end_a - start_a > end_b - start_b) {
        //         second = a; start = start_b; end = end_b;
        //     }
        //     for (unsigned i = start; i < end; ++i) {
        //         unsigned v = var_neighbors[i].first;
        //         double w = var_neighbors[i].second;
        //         if (dsu_.find(v) == second) {
        //             return w;
        //         }
        //     }
        //     return 0.0;
        // };

        // Accumulate total weight and per-node volumes in a single pass
        sum_weights_ = 0.0;
        if (cfg_.use_modularity_guard)
        {
            for (const auto &e : edges)
            {
                sum_weights_ += e.w;
                // Initially each variable is its own component, we expect no self-loops
                comp_vol_[e.u] += e.w;
                comp_vol_[e.v] += e.w;
            }
        }

        intercomp_candidates_.clear();

        for (const auto &e : edges)
        {
            if (!(e.w > 0))
                continue;
            unsigned a = dsu_.find(e.u);
            unsigned b = dsu_.find(e.v);
            if (a == b)
            { // intra-component edge: not a cross-component candidate
                if (cfg_.use_modularity_guard)
                {
                    lb_comp_internal_w_[a] += e.w;
                }
                continue;
            };
            const double connection_distance = (1 / e.w) / d_scale_;
            if (!allow_merge(a, b, connection_distance))
            {
                // Edge did not cause a union; track it for post-processing
                intercomp_candidates_.push_back(e);
                continue;
            }
            // FH criterion passed, now check modularity guard
            if (cfg_.use_modularity_guard)
            {
                // Compute ΔQ tolerance
                double tolerance = dq_tolerance(a, b);
                // Lower-bound of sum of weights of edges between components a and b
                float w_ab_lb = static_cast<float>(sum_weights_to_comp(e.u, b) + sum_weights_to_comp(e.v, a)) - e.w;
                if (accept_by_modularity_lowerbound(a, b, w_ab_lb, tolerance))
                {
                    mod_guard_lb_accepts_++;
                }
                else
                {
                    if (reject_by_modularity_upperbound(a, b, 0))
                    {
                        intercomp_candidates_.push_back(e);
                        mod_guard_ub_rejects_++;
                        continue;
                    }
                    mod_guard_ambiguous_++;
                    switch (cfg_.ambiguous_policy)
                    {
                    case Config::Ambiguous::Accept:
                        // do nothing; we’ll accept below
                        break;
                    case Config::Ambiguous::Reject:
                        intercomp_candidates_.push_back(e);
                        continue;
                    case Config::Ambiguous::GateMargin:
                    {
                        // require the FH distance to be comfortably inside the gate
                        const double g = std::min(gate(a), gate(b));
                        const double margin_ok = (g > 0.0) &&
                                                 ((g - connection_distance) >= cfg_.gate_margin_ratio * g);
                        if (!margin_ok)
                        {
                            intercomp_candidates_.push_back(e);
                            continue;
                        }
                        // else accept
                        break;
                    }
                    }
                }
            }

            // unite returns new representative; we need to merge sizes and min-sim
            // Determine which representative will be the parent by consulting union-by-rank inside dsu
            unsigned r = dsu_.unite(a, b);
            comp_size_[r] = comp_size_[a] + comp_size_[b];
            if (cfg_.use_modularity_guard)
            {
                comp_vol_[r] = comp_vol_[a] + comp_vol_[b];
                lb_comp_internal_w_[r] = lb_comp_internal_w_[a] + lb_comp_internal_w_[b] + e.w;
            }
            // Track maximum distance within the component (use connection_distance)
            double prev_max = std::max(max_dist_[a], max_dist_[b]);
            max_dist_[r] = std::max(prev_max, connection_distance);
        }
    }

    std::vector<SegEdge> GraphSegmenterFH::strongest_inter_component_edges() const
    {
        // Build a map from unordered component pair -> strongest edge (max weight)
        std::unordered_map<std::uint64_t, SegEdge> best;
        best.reserve(intercomp_candidates_.size());

        // Allow early stop when all pairs are covered
        const unsigned num_components = dsu_.components();
        const std::size_t target_pairs = num_components < 2 ? 0 : (num_components * (num_components - 1)) / 2;

        for (const auto &e : intercomp_candidates_)
        {
            unsigned a = dsu_.find_no_compress(e.u);
            unsigned b = dsu_.find_no_compress(e.v);
            if (a == b)
                continue; // now within same component, ignore
            unsigned aa = a, bb = b;
            if (aa > bb)
                std::swap(aa, bb);
            std::uint64_t key = (static_cast<std::uint64_t>(aa) << 32) | static_cast<std::uint64_t>(bb);
            auto it = best.find(key);
            if (it == best.end())
            {
                // store representative endpoints to be clear
                best.emplace(key, SegEdge{aa, bb, e.w});
                if (best.size() == target_pairs)
                    break; // all pairs covered
            }
            // else: edges were processed in descending order; the first is the strongest
        }

        std::vector<SegEdge> out;
        out.reserve(best.size());
        for (auto &kv : best)
            out.push_back(kv.second);
        return out;
    }

} // namespace thesis
