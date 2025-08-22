// Implementation of compact metrics for component sizes.
// See include/thesis/comp_metrics.hpp for API and detailed semantics.
#include "thesis/comp_metrics.hpp"
#include <algorithm>
#include <numeric>
#include <cmath>
#include <limits>

namespace thesis {

// Compute the summary metrics for a given vector of component sizes.
CompSummary summarize_components(const std::vector<uint32_t>& sizes) {
    CompSummary s;
    s.K = static_cast<uint32_t>(sizes.size());
    const uint64_t S64 = std::accumulate(sizes.begin(), sizes.end(), uint64_t{0});
    s.N = static_cast<uint32_t>(S64 > std::numeric_limits<uint32_t>::max() ? std::numeric_limits<uint32_t>::max() : S64);
    const double S = static_cast<double>(S64);

    if (s.K == 0 || S <= 0.0) {
        s.entropyJ = 1.0;
        s.keff = 0.0;
        s.gini = 0.0;
        s.pmax = 0.0;
        return s;
    }

    // keff and pmax
    double sum_p2 = 0.0;
    double pmax = 0.0;
    for (uint32_t x : sizes) {
        if (x == 0u) continue;
        const double p = static_cast<double>(x) / S;
        sum_p2 += p * p;
        if (p > pmax) pmax = p;
    }
    s.keff = (sum_p2 > 0.0) ? (1.0 / sum_p2) : 0.0;
    s.pmax = pmax;

    // Gini coefficient
    if (s.K == 1) {
        s.gini = 0.0;
    } else {
        std::vector<uint32_t> x = sizes;
        std::sort(x.begin(), x.end());
        long double num = 0.0L;
        for (size_t i = 0; i < x.size(); ++i) {
            num += static_cast<long double>(i + 1) * static_cast<long double>(x[i]);
        }
        const long double Kld = static_cast<long double>(s.K);
        const long double Sld = static_cast<long double>(S);
        long double G = (2.0L * num) / (Kld * Sld) - (Kld + 1.0L) / Kld;
        double Gd = static_cast<double>(G);
        if (Gd < 0.0) Gd = 0.0;
        if (Gd > 1.0) Gd = 1.0;
        s.gini = Gd;
    }

    // Entropy evenness (J) in [0,1]
    if (s.K <= 1) {
        s.entropyJ = 1.0;
    } else {
        double H = 0.0;
        for (uint32_t x : sizes) {
            if (x == 0u) continue;
            const double p = static_cast<double>(x) / S;
            H -= p * std::log(p);
        }
        const double denom = std::log(static_cast<double>(s.K));
        s.entropyJ = (denom > 0.0) ? (H / denom) : 1.0;
        if (s.entropyJ < 0.0) s.entropyJ = 0.0;
        if (s.entropyJ > 1.0) s.entropyJ = 1.0;
    }

    return s;
}

} // namespace thesis
