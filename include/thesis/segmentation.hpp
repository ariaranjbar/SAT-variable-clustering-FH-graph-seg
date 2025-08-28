#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cmath>
#include <limits>
#include <utility>
#include <vector>
#include <unordered_map>

#include "thesis/disjoint_set.hpp"
#include "thesis/vig.hpp" // for Edge (u,v,w)

namespace thesis {

// Edge with similarity weight (larger = more similar)
using SegEdge = thesis::Edge;

// Graph segmentation based on the Felzenszwalb–Huttenlocher (FH) predicate with
// optional distance normalization and a modularity guard.
//
// Semantics:
//  - Input edges are undirected similarities (larger weight = more similar).
//  - Distances are d = 1/w; optionally normalized by the median of top-N d’s
//    so k has comparable effect across graphs.
//  - Gate(C) = max_dist(C) + k / |C|^sizeExponent, with max_dist maintained as
//    the maximum internal edge distance observed so far.
//  - Merge rule: allow (a,b) if (1/w)/d_scale <= min(Gate(a), Gate(b)).
//  - Modularity guard (Config::use_modularity_guard): fast lower-bound accept
//    and upper-bound reject tests around ΔQ with resolution gamma; optional
//    annealed tolerance; ambiguous policy configurable.
//  - Edges are processed in descending weight order and stored if they do not
//    merge components. strongest_inter_component_edges() returns one strongest
//    edge per unordered pair of resulting components.
//  - Backbone: union-find with union-by-rank and path compression.

class GraphSegmenterFH {
public:
    // Tunable knobs to control behavior while keeping defaults equivalent to classic FH.
    struct Config {
        // Normalize distances by median of 1/w over top N edges so k is comparable across graphs.
        bool normalize_distances = true;
        std::size_t norm_sample_edges = 1000; // how many top edges to sample for median
        // Size exponent in the gate denominator: tau = k_eff / (|C|^sizeExponent)
        // - 1.0 reproduces FH (k/|C|)
        // - >1.0 makes merges harder for large components
        // - <1.0 makes merges easier for large components
        double sizeExponent = 1.2;

        // Modularity guard:
        bool use_modularity_guard = true;   // turn on the ΔQ gate
        double gamma = 1.0;                 // modularity resolution
        // Annealing (optional): allow slight negative ΔQ for tiny comps; tighten as they grow.
        bool anneal_modularity_guard = true;
        // initial tolerance (dimensionless ΔQ units). 5e-4 is conservative.
        double dq_tolerance0 = 5e-4;
        // scale for annealing; if 0, we auto-set to ~mean degree (2m/n).
        double dq_vscale = 0.0;
        enum class Ambiguous {Accept, Reject, GateMargin};
        Ambiguous ambiguous_policy = Ambiguous::GateMargin;
        double gate_margin_ratio = 0.05; // used only for GateMargin (e.g., 0.05 = need 5% room)
    };

    // Construct a segmenter for n nodes and parameter k.
    explicit GraphSegmenterFH(unsigned n = 0, double k = 50.0);

    // Reset to n nodes, clearing any previous state.
    void reset(unsigned n, double k);

    // Configure behavior; can be called any time before run().
    void set_config(const Config& cfg) { cfg_ = cfg; }
    const Config& config() const { return cfg_; }

    // Run segmentation in-place on the provided edges.
    // Edges will be sorted descending by weight.
    void run(std::vector<SegEdge>& edges);

    // After run(), compute strongest inter-component edges.
    // Returns one edge per unordered pair of components (u,v) with maximum similarity weight.
    // The endpoints u,v are component representatives (roots) at the end of segmentation.
    // If there is no edge between two components in the input, it won't appear in the result.
    std::vector<SegEdge> strongest_inter_component_edges() const;

    // Access the non-union edges that connect two different components at the
    // time they were considered (i.e., potential inter-component connections).
    // Stored in the same descending order used during segmentation.
    const std::vector<SegEdge>& inter_component_candidates() const { return intercomp_candidates_; }

    // Accessors
    unsigned node_count() const { return static_cast<unsigned>(comp_size_.size()); }
    unsigned num_components() const { return dsu_.components(); }

    // Representative/root id for x (0..n-1). Non-const compressing find.
    unsigned component(unsigned x) { return dsu_.find(x); }
    // Const variant without compression.
    unsigned component_no_compress(unsigned x) const { return dsu_.find_no_compress(x); }

    // Size of the component whose representative is r.
    unsigned comp_size(unsigned r) const { return comp_size_[r]; }

    // Minimum similarity weight observed within the component (representative r).
    double comp_min_weight(unsigned r) const { return max_dist_[r] > 0 ? 1.0 / max_dist_[r] : std::numeric_limits<double>::infinity(); }

    // Effective scaling applied to k (median of base distances); informative only.
    double k_scale() const { return d_scale_; }

    // Number of modularity guard forced rejections forced acceptances, and ambiguous cases.
    unsigned mod_guard_lb_accepts() const { return mod_guard_lb_accepts_; }
    unsigned mod_guard_ub_rejects() const { return mod_guard_ub_rejects_; }
    unsigned mod_guard_ambiguous() const { return mod_guard_ambiguous_; }

private:
    inline double gate(unsigned r) const {
        // Gate bias controlled by k and the size exponent in the denominator.
        const double size_term = std::pow(static_cast<double>(comp_size_[r]), cfg_.sizeExponent);
        const double tau = k_ / (size_term > 0 ? size_term : 1.0);
        return max_dist_[r] + tau;
    }
    inline bool allow_merge(unsigned a, unsigned b, double connection_distance) const {
        const double ga = gate(a);
        const double gb = gate(b);
        return connection_distance <= (ga < gb ? ga : gb);
    }
    inline double dq_tolerance(unsigned a, unsigned b) const {
        if (!cfg_.anneal_modularity_guard) return 0.0; // static guard
        const double maxVol = std::max(comp_vol_[a], comp_vol_[b]);
        double vscale = cfg_.dq_vscale;
        if (!(vscale > 0.0)) {
            const double n = static_cast<double>(node_count());
            vscale = (n > 0.0) ? std::max(1.0, (2.0 * sum_weights_) / n) : 1.0; // ~mean degree
        }
        return -cfg_.dq_tolerance0 * std::exp(-maxVol / vscale); // tiny negative early, goes to 0
    }
    inline double dq_lower_bound(unsigned a, unsigned b, double ab_w) const {
        // ΔQ_LB = w/m - γ * vol[a]*vol[b] / (2 m^2)
        const double m = sum_weights_;
        if (!(m > 0.0)) return -std::numeric_limits<double>::infinity();
        return (ab_w / m) - (cfg_.gamma * comp_vol_[a] * comp_vol_[b]) / (2.0 * m * m);
    }
    inline double dq_upper_bound(unsigned a, unsigned b) const {
        const double va = comp_vol_[a], vb = comp_vol_[b], m = sum_weights_;
        // Upper bounds on cuts
        const double cutA_ub = std::max(0.0, va - 2.0 * lb_comp_internal_w_[a]);
        const double cutB_ub = std::max(0.0, vb - 2.0 * lb_comp_internal_w_[b]);
        double eab_ub = std::min(cutA_ub, cutB_ub);
        // Trivial bound (optional – never worse)
        eab_ub = std::min(eab_ub, std::min(va, vb));
        // Best-case ΔQ given that e_ab ≤ eab_ub
        const double dq_max = (eab_ub / m) - (cfg_.gamma * va * vb) / (2.0 * m * m);
        return dq_max;
    }
    inline bool accept_by_modularity_lowerbound(unsigned a, unsigned b, double ab_w, double tol) const {
        if (!(cfg_.use_modularity_guard) || !(sum_weights_ > 0.0)) return true; // accept
        const double dq_min = dq_lower_bound(a, b, ab_w);
        return dq_min >= tol; // if worst-case is still above tolerance, accept
    }
    inline bool reject_by_modularity_upperbound(unsigned a, unsigned b, double tol) const {
        if (!(cfg_.use_modularity_guard) || !(sum_weights_ > 0.0)) return false; // don't reject
        const double dq_max = dq_upper_bound(a, b);
        return dq_max < tol; // if even best-case is below tolerance, reject
    }
    static inline std::uint64_t pair_key(unsigned a, unsigned b) {
        if (a > b) std::swap(a, b);
        return (static_cast<std::uint64_t>(a) << 32) | static_cast<std::uint64_t>(b);
    }

    double sum_weights_{0};
    DisjointSets dsu_{};
    std::vector<unsigned> comp_size_{};
    std::vector<double> max_dist_{};
    std::vector<double> lb_comp_internal_w_{}; // Lower-bound of internal component weights
    std::vector<double> comp_vol_{};
    double k_ = 50.0;
    Config cfg_{}; // tuning knobs
    // Scale factor for distances (median of base distances 1/w computed in run())
    double d_scale_ = 1.0;
    // Non-union edges that were cross-component when processed (descending weight order).
    // These are candidates for strongest inter-component connections.
    std::vector<SegEdge> intercomp_candidates_{};
    // Track modularity guard rejections
    unsigned mod_guard_ub_rejects_{0};
    unsigned mod_guard_ambiguous_{0};
    unsigned mod_guard_lb_accepts_{0};
};

} // namespace thesis
