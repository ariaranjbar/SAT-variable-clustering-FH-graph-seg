#include "thesis/vig.hpp"

#include <unordered_map>
#include <algorithm>
#include <stdexcept>
#include <utility>
#include <cmath>

namespace thesis {
namespace detail {

static inline uint64_t pack_pair(uint32_t u, uint32_t v) {
  return (static_cast<uint64_t>(u) << 32) | static_cast<uint64_t>(v);
}

static inline std::pair<uint32_t,uint32_t> unpack_pair(uint64_t key) {
  uint32_t u = static_cast<uint32_t>(key >> 32);
  uint32_t v = static_cast<uint32_t>(key & 0xffffffffu);
  return {u, v};
}

static inline void normalize_clause_vars(const std::vector<int>& clause_lits,
                                         uint32_t nvars,
                                         std::vector<uint32_t>& out_vars_sorted_unique) {
  out_vars_sorted_unique.clear();
  out_vars_sorted_unique.reserve(clause_lits.size());
  for (int lit : clause_lits) {
    int v = std::abs(lit) - 1;
    if (v >= 0 && static_cast<uint32_t>(v) < nvars) {
      out_vars_sorted_unique.push_back(static_cast<uint32_t>(v));
    }
  }
  std::sort(out_vars_sorted_unique.begin(), out_vars_sorted_unique.end());
  out_vars_sorted_unique.erase(std::unique(out_vars_sorted_unique.begin(), out_vars_sorted_unique.end()),
                               out_vars_sorted_unique.end());
}

static inline double inv_binom2(size_t s) {
  return 2.0 / (static_cast<double>(s) * static_cast<double>(s - 1));
}

} // namespace detail

VIG build_vig_naive(const CNF& cnf,
                    unsigned clause_size_threshold,
                    bool sort_descending_by_weight) {
  VIG result;
  result.n = cnf.get_variable_count();
  const auto& clauses = cnf.get_clauses();

  using detail::pack_pair;
  using detail::unpack_pair;
  using detail::normalize_clause_vars;
  using detail::inv_binom2;

  std::unordered_map<uint64_t, double> agg;
  agg.reserve(static_cast<size_t>(cnf.get_clause_count() * 2u));

  std::vector<uint32_t> vars;
  vars.reserve(64);

  for (const auto& c : clauses) {
    normalize_clause_vars(c, result.n, vars);
    const size_t s = vars.size();
    if (s < 2) continue;
    if (s > clause_size_threshold) continue;

    const double w_pair = inv_binom2(s);

    for (size_t i = 0; i + 1 < s; ++i) {
      uint32_t a = vars[i];
      for (size_t j = i + 1; j < s; ++j) {
        uint32_t b = vars[j];
        const uint64_t key = pack_pair(a, b);
        agg[key] += w_pair;
      }
    }
  }

  result.edges.reserve(agg.size());
  for (const auto& kv : agg) {
    auto [u, v] = detail::unpack_pair(kv.first);
    result.edges.push_back(Edge{u, v, kv.second});
  }

  if (sort_descending_by_weight) {
    std::sort(result.edges.begin(), result.edges.end(),
              [](const Edge& A, const Edge& B) {
                if (A.w != B.w) return A.w > B.w;
                if (A.u != B.u) return A.u < B.u;
                return A.v < B.v;
              });
  }

  return result;
}

struct Triple { uint32_t a; uint32_t b; double w; };
struct Batch { uint32_t start; uint32_t end; };

VIG build_vig_optimized(const CNF& cnf,
                        unsigned clause_size_threshold,
                        std::size_t max_buffer_contributions,
                        bool sort_descending_by_weight) {
  VIG result;
  result.n = cnf.get_variable_count();
  const auto& clauses = cnf.get_clauses();
  const uint32_t n = result.n;

  using detail::normalize_clause_vars;
  using detail::inv_binom2;

  if (n == 0) return result;
  if (max_buffer_contributions == 0) {
    throw std::invalid_argument("max_buffer_contributions must be > 0");
  }

  std::vector<uint64_t> contrib_counts(n, 0);
  std::vector<uint32_t> vars; vars.reserve(64);

  for (const auto& c : clauses) {
    normalize_clause_vars(c, n, vars);
    const size_t s = vars.size();
    if (s < 2) continue;
    if (s > clause_size_threshold) continue;
    for (size_t i = 0; i + 1 < s; ++i) {
      contrib_counts[vars[i]] += static_cast<uint64_t>(s - 1 - i);
    }
  }

  std::vector<Batch> batches;
  {
    uint32_t start = 0;
    uint64_t accum = 0;
    for (uint32_t v = 0; v < n; ++v) {
      if (accum + contrib_counts[v] > static_cast<uint64_t>(max_buffer_contributions) && v > start) {
        batches.push_back(Batch{start, static_cast<uint32_t>(v - 1)});
        start = v;
        accum = contrib_counts[v];
      } else {
        accum += contrib_counts[v];
      }
    }
    if (start < n) batches.push_back(Batch{start, n - 1});
  }

  std::unordered_map<uint64_t, double> agg;
  {
    uint64_t total_pairs_est = 0;
    for (auto c : contrib_counts) total_pairs_est += c;
    agg.reserve(static_cast<size_t>(std::min<uint64_t>(total_pairs_est, 3ull * 1000000ull)));
  }

  std::vector<Triple> buffer;
  std::vector<uint64_t> offsets;
  std::vector<uint64_t> write_ptrs;
  std::vector<double>  accum(n, 0.0);
  std::vector<uint32_t> visited; visited.reserve(1024);

  for (const Batch& batch : batches) {
    const uint32_t sV = batch.start;
    const uint32_t eV = batch.end;
    if (sV > eV) continue;

    const size_t batch_len = static_cast<size_t>(eV - sV + 1);
    offsets.assign(batch_len, 0);
    {
      uint64_t pref = 0;
      for (uint32_t a = sV; a <= eV; ++a) {
        offsets[a - sV] = pref;
        pref += contrib_counts[a];
      }
      buffer.assign(static_cast<size_t>(offsets.back() + contrib_counts[eV]), Triple{0,0,0.0});
      write_ptrs = offsets;
    }

    for (const auto& c : clauses) {
      normalize_clause_vars(c, n, vars);
      const size_t s = vars.size();
      if (s < 2) continue;
      if (s > clause_size_threshold) continue;

      const double w_pair = inv_binom2(s);

      for (size_t i = 0; i + 1 < s; ++i) {
        uint32_t a = vars[i];
        if (a < sV || a > eV) continue;

        uint64_t pos = write_ptrs[a - sV];
        for (size_t j = i + 1; j < s; ++j) {
          uint32_t b = vars[j];
          buffer[pos++] = Triple{a, b, w_pair};
        }
        write_ptrs[a - sV] = pos;
      }
    }

    visited.clear();
    for (uint32_t a = sV; a <= eV; ++a) {
      const uint64_t begin = offsets[a - sV];
      const uint64_t count = contrib_counts[a];
      const uint64_t end   = begin + count;

      for (uint64_t p = begin; p < end; ++p) {
        const Triple& t = buffer[p];
        if (accum[t.b] == 0.0) visited.push_back(t.b);
        accum[t.b] += t.w;
      }

      for (uint32_t b : visited) {
        const double w = accum[b];
        accum[b] = 0.0;
        const uint64_t key = detail::pack_pair(a, b);
        auto it = agg.find(key);
        if (it == agg.end()) agg.emplace(key, w);
        else it->second += w;
      }
      visited.clear();
    }
  }

  result.edges.reserve(agg.size());
  for (const auto& kv : agg) {
    auto uv = detail::unpack_pair(kv.first);
    result.edges.push_back(Edge{uv.first, uv.second, kv.second});
  }

  if (sort_descending_by_weight) {
    std::sort(result.edges.begin(), result.edges.end(),
              [](const Edge& A, const Edge& B) {
                if (A.w != B.w) return A.w > B.w;
                if (A.u != B.u) return A.u < B.u;
                return A.v < B.v;
              });
  }

  return result;
}

} // namespace thesis
