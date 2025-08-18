#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cmath>
#include <iostream>
#include <limits>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

// ==== Your CNF class is assumed to exist in this namespace ====
namespace thesis {

class CNF {
  bool valid = false;
  unsigned int variable_count = 0;
  unsigned int clause_count = 0;
  std::vector<std::vector<int>> clauses;

public:
  CNF(const std::string &file_path, bool variable_compaction = true); // assume implemented elsewhere

  bool is_valid() const { return valid; }
  const std::vector<std::vector<int>> &get_clauses() const { return clauses; }
  unsigned int get_variable_count() const { return variable_count; }
  unsigned int get_clause_count() const { return clause_count; }
};

// ---------- VIG data structures ----------
struct Edge {
  uint32_t u;    // 0-based variable id, canonical u < v
  uint32_t v;    // 0-based variable id
  double   w;    // aggregated weight
};

struct VIG {
  uint32_t n;               // number of variables
  std::vector<Edge> edges;  // aggregated edges (u < v), typically sorted by descending w
};

// ---------- Helpers ----------
namespace detail {

// Pack an ordered pair (u < v) into 64 bits for hashing/aggregation
static inline uint64_t pack_pair(uint32_t u, uint32_t v) {
  return (static_cast<uint64_t>(u) << 32) | static_cast<uint64_t>(v);
}

// Extract back (only used for conversion from map to vector)
static inline std::pair<uint32_t,uint32_t> unpack_pair(uint64_t key) {
  uint32_t u = static_cast<uint32_t>(key >> 32);
  uint32_t v = static_cast<uint32_t>(key & 0xffffffffu);
  return {u, v};
}

// Normalize and uniquify a clause into sorted 0-based variable ids, ignoring polarity.
static inline void normalize_clause_vars(const std::vector<int>& clause_lits,
                                         uint32_t nvars,
                                         std::vector<uint32_t>& out_vars_sorted_unique) {
  out_vars_sorted_unique.clear();
  out_vars_sorted_unique.reserve(clause_lits.size());
  for (int lit : clause_lits) {
    int v = std::abs(lit) - 1;   // DIMACS is 1-based
    if (v >= 0 && static_cast<uint32_t>(v) < nvars) {
      out_vars_sorted_unique.push_back(static_cast<uint32_t>(v));
    }
  }
  std::sort(out_vars_sorted_unique.begin(), out_vars_sorted_unique.end());
  out_vars_sorted_unique.erase(std::unique(out_vars_sorted_unique.begin(),
                                           out_vars_sorted_unique.end()),
                               out_vars_sorted_unique.end());
}

// 1 / binom(s,2) as double, with s >= 2 assumed
static inline double inv_binom2(size_t s) {
  // binom(s,2) = s*(s-1)/2
  return 2.0 / (static_cast<double>(s) * static_cast<double>(s - 1));
}

} // namespace detail

// ===============================================================
// NAIVE VIG BUILDER
// ===============================================================
VIG build_vig_naive(const CNF& cnf,
                    unsigned clause_size_threshold = std::numeric_limits<unsigned>::max(),
                    bool sort_descending_by_weight = true) {
  VIG result;
  result.n = cnf.get_variable_count();
  const auto& clauses = cnf.get_clauses();

  using detail::pack_pair;
  using detail::unpack_pair;
  using detail::normalize_clause_vars;
  using detail::inv_binom2;

  // Aggregation map: (u,v) -> w
  std::unordered_map<uint64_t, double> agg;
  agg.reserve(static_cast<size_t>(cnf.get_clause_count() * 2u)); // rough guess

  std::vector<uint32_t> vars; // reusable buffer
  vars.reserve(64);

  for (const auto& c : clauses) {
    normalize_clause_vars(c, result.n, vars);
    const size_t s = vars.size();
    if (s < 2) continue;
    if (s > clause_size_threshold) continue;

    const double w_pair = inv_binom2(s);

    // Accumulate over all pairs (i<j)
    for (size_t i = 0; i + 1 < s; ++i) {
      uint32_t a = vars[i];
      for (size_t j = i + 1; j < s; ++j) {
        uint32_t b = vars[j];
        const uint64_t key = pack_pair(a, b);
        agg[key] += w_pair;
      }
    }
  }

  // Move to vector<Edge>
  result.edges.reserve(agg.size());
  for (const auto& kv : agg) {
    auto [u, v] = unpack_pair(kv.first);
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

// ===============================================================
// OPTIMIZED (BATCHED/OFFSET) VIG BUILDER
//   - Precompute per-variable contribution counts (sizes)
//   - Partition variables into batches that fit a fixed buffer capacity (#contribs)
//   - For each batch: fill buffer with (a,b,w) triples where a in batch, b>a
//   - Aggregate per 'a' using a fixed-size accumulator with a visited list
// ===============================================================
struct Triple {
  uint32_t a;
  uint32_t b;
  double   w;
};

struct Batch { uint32_t start; uint32_t end; }; // inclusive

VIG build_vig_optimized(const CNF& cnf,
                        unsigned clause_size_threshold,
                        size_t max_buffer_contributions,   // capacity in #triples (not bytes)
                        bool sort_descending_by_weight = true) {
  VIG result;
  result.n = cnf.get_variable_count();
  const auto& clauses = cnf.get_clauses();
  const uint32_t n = result.n;

  using detail::normalize_clause_vars;
  using detail::inv_binom2;

  // ---------- Phase 0: Edge-case shortcuts ----------
  if (n == 0) return result;
  if (max_buffer_contributions == 0) {
    throw std::invalid_argument("max_buffer_contributions must be > 0");
  }

  // ---------- Phase 1: Preprocess per-variable contribution counts ----------
  std::vector<uint64_t> contrib_counts(n, 0); // how many (a,b) entries 'a' will produce (with b>a)
  std::vector<uint32_t> vars; vars.reserve(64);

  for (const auto& c : clauses) {
    normalize_clause_vars(c, n, vars);
    const size_t s = vars.size();
    if (s < 2) continue;
    if (s > clause_size_threshold) continue;

    // For sorted vars, index i contributes (s-1-i) pairs as 'a'
    for (size_t i = 0; i + 1 < s; ++i) {
      contrib_counts[vars[i]] += static_cast<uint64_t>(s - 1 - i);
    }
  }

  // ---------- Phase 2: Partition variables into batches by capacity ----------
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

  // ---------- Phase 3: Process each batch ----------
  // Global accumulator: (u,v) -> w. We keep it as a map to avoid a second pass over all batches.
  std::unordered_map<uint64_t, double> agg;
  {
    // Try a decent reserve (heuristic)
    uint64_t total_pairs_est = 0;
    for (auto c : contrib_counts) total_pairs_est += c;
    agg.reserve(static_cast<size_t>(std::min<uint64_t>(total_pairs_est, 3ull * 1000000ull)));
  }

  // Per-batch working buffers
  std::vector<Triple> buffer;                 // size = sum contrib_counts[a] for a in batch
  std::vector<uint64_t> offsets;              // starting offset per 'a' in buffer (relative)
  std::vector<uint64_t> write_ptrs;           // moving write pointer per 'a'
  std::vector<double>  accum(n, 0.0);         // fixed-size accumulator by 'b'
  std::vector<uint32_t> visited; visited.reserve(1024);

  for (const Batch& batch : batches) {
    const uint32_t sV = batch.start;
    const uint32_t eV = batch.end;
    if (sV > eV) continue;

    // Compute local sizes and prefix offsets for [sV..eV]
    const size_t batch_len = static_cast<size_t>(eV - sV + 1);
    offsets.assign(batch_len, 0);
    {
      uint64_t pref = 0;
      for (uint32_t a = sV; a <= eV; ++a) {
        offsets[a - sV] = pref;
        pref += contrib_counts[a];
      }
      buffer.assign(static_cast<size_t>(offsets.back() + contrib_counts[eV]), Triple{0,0,0.0});
      write_ptrs = offsets; // copy starting offsets
    }

    // Pass A: Fill buffer with (a,b,w) triples for this batch
    for (const auto& c : clauses) {
      normalize_clause_vars(c, n, vars);
      const size_t s = vars.size();
      if (s < 2) continue;
      if (s > clause_size_threshold) continue;

      const double w_pair = inv_binom2(s);

      // For each a in batch, append its pairs (a,b) with b>a
      for (size_t i = 0; i + 1 < s; ++i) {
        uint32_t a = vars[i];
        if (a < sV || a > eV) continue;

        uint64_t pos = write_ptrs[a - sV];
        for (size_t j = i + 1; j < s; ++j) {
          uint32_t b = vars[j]; // b > a due to sorting
          buffer[pos++] = Triple{a, b, w_pair};
        }
        write_ptrs[a - sV] = pos;
      }
    }

    // Pass B: Aggregate entries for each 'a' (use fixed-size accum by 'b' + visited list)
    visited.clear();
    for (uint32_t a = sV; a <= eV; ++a) {
      const uint64_t begin = offsets[a - sV];
      const uint64_t count = contrib_counts[a];
      const uint64_t end   = begin + count;

      // Accumulate into 'accum[b]'
      for (uint64_t p = begin; p < end; ++p) {
        const Triple& t = buffer[p];
        if (accum[t.b] == 0.0) visited.push_back(t.b);
        accum[t.b] += t.w;
      }

      // Flush for this 'a' into the global map, then reset visited accum slots
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

  // ---------- Phase 4: Move agg → result.edges ----------
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

// ===============================================================
// Optional: tiny CLI wrapper (for quick tests / benchmarking)
//   Usage: ./vig_builders -i file.cnf [-tau N] [-maxbuf M] [--naive|--opt]
//   Prints "edges=<count>" and basic stats to stdout.
// ===============================================================
#ifdef THESIS_VIG_MAIN
#include <chrono>

int main(int argc, char** argv) {
  using namespace thesis;
  std::string path;
  unsigned tau = std::numeric_limits<unsigned>::max();
  size_t maxbuf = 50'000'000; // default max contributions in optimized mode
  bool use_naive = false, use_opt = true;

  for (int i = 1; i < argc; ++i) {
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
  }

  if (path.empty()) {
    std::cerr << "Usage: " << argv[0] << " -i file.cnf [-tau N|inf] [-maxbuf M] [--naive|--opt]\n";
    return 1;
  }

  CNF cnf(path, /*variable_compaction=*/true);
  if (!cnf.is_valid()) {
    std::cerr << "Failed to parse CNF: " << path << "\n";
    return 2;
  }

  auto t0 = std::chrono::steady_clock::now();
  VIG g;
  if (use_naive) {
    g = build_vig_naive(cnf, tau, /*sort_desc=*/true);
  } else {
    g = build_vig_optimized(cnf, tau, maxbuf, /*sort_desc=*/true);
  }
  auto t1 = std::chrono::steady_clock::now();
  double sec = std::chrono::duration<double>(t1 - t0).count();

  std::cout << "vars=" << g.n
            << " edges=" << g.edges.size()
            << " time_sec=" << sec
            << " impl=" << (use_naive ? "naive" : "opt")
            << " tau=" << (tau == std::numeric_limits<unsigned>::max() ? -1 : (int)tau)
            << "\n";
  return 0;
}
#endif
