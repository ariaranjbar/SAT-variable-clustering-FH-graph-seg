#include "thesis/segmentation.hpp"
#include <numeric>
#include <unordered_map>
#include <unordered_set>

namespace thesis {

GraphSegmenterFH::GraphSegmenterFH(unsigned n, double k) { reset(n, k); }

void GraphSegmenterFH::reset(unsigned n, double k) {
    dsu_.reset(n);
    comp_size_.assign(n, 1);
    max_dist_.assign(n, 0);
    k_ = k;
    inter_comp_candidates_.clear();
}

static inline bool edge_desc(const SegEdge& a, const SegEdge& b) { return a.w > b.w; }

void GraphSegmenterFH::run(std::vector<SegEdge>& edges) {
    std::sort(edges.begin(), edges.end(), edge_desc);
    inter_comp_candidates_.clear();
    for (const auto& e : edges) {
        unsigned a = dsu_.find(e.u);
        unsigned b = dsu_.find(e.v);
        if (a == b) continue; // intra-component edge: not a cross-component candidate
        const double connection_distance = 1/e.w;
        const double gate_a = gate(a);
        const double gate_b = gate(b);
        if (connection_distance <= (gate_a < gate_b ? gate_a : gate_b)) {
            // unite returns new representative; we need to merge sizes and min-sim
            // Determine which representative will be the parent by consulting union-by-rank inside dsu
            unsigned r = dsu_.unite(a, b);
            comp_size_[r] = comp_size_[a] + comp_size_[b];
            // Track maximum distance within the component (use connection_distance)
            double prev_max = std::max(max_dist_[a], max_dist_[b]);
            max_dist_[r] = std::max(prev_max, connection_distance);
        } else {
            // Edge did not cause a union; track it for post-processing
            inter_comp_candidates_.push_back(e);
        }
    }
}

double GraphSegmenterFH::gate(unsigned r) const {
    const double tau = k_ / static_cast<double>(comp_size_[r]);
    return max_dist_[r] + tau;

}

std::vector<SegEdge> GraphSegmenterFH::strongest_inter_component_edges() const {
    // Build a map from unordered component pair -> strongest edge (max weight)
    std::unordered_map<std::uint64_t, SegEdge> best;
    best.reserve(inter_comp_candidates_.size());

    // Compute final number of components to allow early stop when all pairs are covered
    std::unordered_set<unsigned> reps;
    reps.reserve(node_count());
    for (unsigned i = 0, n = node_count(); i < n; ++i) {
        reps.insert(dsu_.find_no_compress(i));
    }
    const std::size_t target_pairs = reps.size() < 2 ? 0 : (reps.size() * (reps.size() - 1)) / 2;

    for (const auto& e : inter_comp_candidates_) {
        unsigned a = dsu_.find_no_compress(e.u);
        unsigned b = dsu_.find_no_compress(e.v);
        if (a == b) continue; // now within same component, ignore
        unsigned aa = a, bb = b;
        if (aa > bb) std::swap(aa, bb);
        std::uint64_t key = (static_cast<std::uint64_t>(aa) << 32) | static_cast<std::uint64_t>(bb);
        auto it = best.find(key);
        if (it == best.end()) {
            // store representative endpoints to be clear
            best.emplace(key, SegEdge{aa, bb, e.w});
            if (best.size() == target_pairs) break; // all pairs covered
        }
        // else: edges were processed in descending order; the first is the strongest
    }

    std::vector<SegEdge> out;
    out.reserve(best.size());
    for (auto& kv : best) out.push_back(kv.second);
    return out;
}

} // namespace thesis
