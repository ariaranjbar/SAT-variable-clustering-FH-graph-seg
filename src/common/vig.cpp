// ----------------------------------------------------------------------------
// vig.cpp
//
// Variable Incidence Graph (VIG) builders: naive (single-threaded) and
// optimized (multi-threaded, memory-aware).
//
// Optimized-path highlights (final design):
//  - CNF clauses are pre-normalized at load time (sorted by |lit|, deduped, no tautologies).
//  - O(s) phase-1 per clause for per-variable contribution counts.
//  - Memory-aware batching of variable ranges.
//  - ONE-PASS round with “batched atomics”:
//      * for each u in a clause, atomic fetch_add(s-1-i) once,
//        then write a contiguous run of neighbors to the batch buffer.
//    => only 1 clause scan per round, few atomics, deterministic per-a multiset.
//  - Per-a accumulation by sort-and-reduce (local, cache-friendly).
//  - 32-bit offsets/counts with overflow guards.
//  - Thread pool + std::barrier (no spawn/join per round).
//  - Detailed VIG_OPT_DEBUG planning/stats + memory breakdown.
// ----------------------------------------------------------------------------

#include "thesis/vig.hpp"

#include <algorithm>
#include <atomic>
#include <barrier>
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <iterator>
#include <iostream>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

namespace thesis
{
  namespace detail
  {
    // Tracks transient allocations (ActiveBatch buffers per round, var_to_active while active).
    struct MemGauge
    {
      std::atomic<size_t> current{0}, peak{0};
      void add(size_t bytes)
      {
        const size_t cur = current.fetch_add(bytes, std::memory_order_relaxed) + bytes;
        size_t p = peak.load(std::memory_order_relaxed);
        while (cur > p && !peak.compare_exchange_weak(p, cur, std::memory_order_relaxed)) {}
      }
      void sub(size_t bytes) { current.fetch_sub(bytes, std::memory_order_relaxed); }
    };

    static MemGauge g_mem_gauge;

    static inline uint64_t pack_pair(uint32_t u, uint32_t v)
    {
      return (static_cast<uint64_t>(u) << 32) | static_cast<uint64_t>(v);
    }
    static inline std::pair<uint32_t, uint32_t> unpack_pair(uint64_t key)
    {
      uint32_t u = static_cast<uint32_t>(key >> 32);
      uint32_t v = static_cast<uint32_t>(key & 0xffffffffu);
      return {u, v};
    }

    // ----------------------------------------------------------------------
    // Counting allocator to measure exact bytes requested by unordered_map.
    // Enabled only when THESIS_VIG_MEMORY_ACCOUNTING is defined.
    // ----------------------------------------------------------------------
#if defined(THESIS_VIG_MEMORY_ACCOUNTING)
    struct CountingAllocatorGlobalBytes { static std::atomic<size_t> bytes; };
    inline std::atomic<size_t> CountingAllocatorGlobalBytes::bytes{0};

    template <class T>
    struct CountingAllocator
    {
      using value_type = T;
      using propagate_on_container_move_assignment = std::true_type;
      using is_always_equal = std::true_type;

      // One shared counter for all T via a reference alias.
      static std::atomic<size_t> &bytes;

      CountingAllocator() noexcept {}
      template <class U>
      CountingAllocator(const CountingAllocator<U> &) noexcept {}

      T *allocate(std::size_t n)
      {
        const size_t b = n * sizeof(T);
        bytes.fetch_add(b, std::memory_order_relaxed);
        return static_cast<T *>(::operator new(b));
      }
      void deallocate(T *p, std::size_t n) noexcept
      {
        const size_t b = n * sizeof(T);
        bytes.fetch_sub(b, std::memory_order_relaxed);
        ::operator delete(p);
      }

      template <class U>
      struct rebind { using other = CountingAllocator<U>; };
    };

    template <class T>
    std::atomic<size_t> &CountingAllocator<T>::bytes = CountingAllocatorGlobalBytes::bytes;

    template <class T, class U>
    constexpr bool operator==(const CountingAllocator<T> &, const CountingAllocator<U> &) noexcept { return true; }
    template <class T, class U>
    constexpr bool operator!=(const CountingAllocator<T> &, const CountingAllocator<U> &) noexcept { return false; }
#endif

    static inline double inv_binom2(size_t s)
    {
      return 2.0 / (static_cast<double>(s) * static_cast<double>(s - 1));
    }

    struct OptPlan
    {
      size_t total_contrib;
      size_t per_thread_buffer;
      size_t target_passes;
    };

    static inline OptPlan plan(size_t total_contrib, unsigned t, size_t user_maxbuf)
    {
      const size_t denom  = std::max<size_t>(1, t > 0 ? (t - 1) : 0);
      const size_t per    = std::max<size_t>(1, user_maxbuf / denom);
      const size_t passes = (per > 0 && t > 0)
                            ? ((total_contrib + per * t - 1) / (per * t))
                            : 0;
      return OptPlan{total_contrib, per, passes};
    }

  } // namespace detail

  // --------------------------------------------------------------------------
  // Naive single-threaded builder (hash-map aggregation).
  // --------------------------------------------------------------------------
  VIG build_vig_naive(const CNF &cnf,
                      unsigned clause_size_threshold,
                      bool sort_descending_by_weight)
  {
    VIG result;
    result.n = cnf.get_variable_count();
    const auto &clauses = cnf.get_clauses();

    using detail::inv_binom2;
    using detail::pack_pair;
    using detail::unpack_pair;

  using KV  = std::pair<const uint64_t, double>;
#if defined(THESIS_VIG_MEMORY_ACCOUNTING)
  using Map = std::unordered_map<uint64_t, double,
                   std::hash<uint64_t>, std::equal_to<uint64_t>,
                   detail::CountingAllocator<KV>>;
  // Reset the counting allocator bytes before use.
  detail::CountingAllocator<KV>::bytes.store(0, std::memory_order_relaxed);
#else
  using Map = std::unordered_map<uint64_t, double>;
#endif

  Map agg;
    agg.reserve(static_cast<size_t>(cnf.get_clause_count() * 2u));

    for (const auto &c : clauses)
    {
      const size_t s = c.size();
      if (s < 2 || s > clause_size_threshold) continue;

      const double w_pair = inv_binom2(s);
      for (size_t i = 0; i + 1 < s; i++)
        for (size_t j = i + 1; j < s; j++)
        {
          const uint32_t a = static_cast<uint32_t>(std::abs(c[i]) - 1);
          const uint32_t b = static_cast<uint32_t>(std::abs(c[j]) - 1);
          const uint32_t u = std::min(a, b);
          const uint32_t v = std::max(a, b);
          agg[pack_pair(u, v)] += w_pair;
        }
    }

    result.edges.reserve(agg.size());
    for (const auto &kv : agg)
    {
      auto [u, v] = detail::unpack_pair(kv.first);
      result.edges.push_back(Edge{u, v, kv.second});
    }

    if (sort_descending_by_weight)
    {
      std::sort(result.edges.begin(), result.edges.end(),
                [](const Edge &A, const Edge &B)
                {
                  if (A.w != B.w) return A.w > B.w;
                  if (A.u != B.u) return A.u < B.u;
                  return A.v < B.v;
                });
    }

  // Memory accounting: only if enabled at compile time.
#if defined(THESIS_VIG_MEMORY_ACCOUNTING)
  const size_t map_bytes_exact = detail::CountingAllocator<KV>::bytes.load(std::memory_order_relaxed);
  const size_t result_edges_bytes = result.edges.capacity() * sizeof(Edge);
  result.aggregation_memory = map_bytes_exact + result_edges_bytes;
#else
  result.aggregation_memory = 0;
#endif

    return result;
  }

  // --------------------------------------------------------------------------
  // Optimized multi-threaded builder (memory-aware batching).
  // --------------------------------------------------------------------------
  struct Batch { uint32_t start, end; };
  struct BufferEntry { uint32_t b; float w; };

  VIG build_vig_optimized(const CNF &cnf,
                          unsigned clause_size_threshold,
                          std::size_t max_buffer_contributions,
                          bool sort_descending_by_weight)
  {
    const unsigned fallback_threads =
        std::max(1u, std::thread::hardware_concurrency() ? std::thread::hardware_concurrency() : 1u);
    return build_vig_optimized(cnf, clause_size_threshold, max_buffer_contributions,
                               sort_descending_by_weight, fallback_threads);
  }

  VIG build_vig_optimized(const CNF &cnf,
                          unsigned clause_size_threshold,
                          std::size_t max_buffer_contributions,
                          bool sort_descending_by_weight,
                          unsigned num_threads)
  {
    using detail::inv_binom2;

    VIG result;
    result.n = cnf.get_variable_count();
    const auto &clauses = cnf.get_clauses();
    const uint32_t n = result.n;

  // Reset transient-memory gauge for this build if accounting is enabled.
#if defined(THESIS_VIG_MEMORY_ACCOUNTING)
  detail::g_mem_gauge.current.store(0, std::memory_order_relaxed);
  detail::g_mem_gauge.peak.store(0, std::memory_order_relaxed);
#endif

    if (n == 0) return result;
    if (max_buffer_contributions == 0)
      throw std::invalid_argument("max_buffer_contributions must be > 0");
    if (num_threads == 0)
      throw std::invalid_argument("num_threads must be > 0");

    const unsigned t = std::max(1u, num_threads);

    // ---------- Phase 1: per-variable contribution counts (O(s)) ----------
    // Also track the maximum clause size actually observed (bounded by threshold)
    size_t max_clause_size_observed = 0;
    std::vector<uint64_t> contrib_counts(n, 0);
    for (const auto &c : clauses)
    {
      const size_t s = c.size();
      if (s < 2 || s > clause_size_threshold) continue;
      if (s > max_clause_size_observed) max_clause_size_observed = s;
      for (size_t i = 0; i + 1 < s; ++i)
      {
        const uint32_t a = static_cast<uint32_t>(std::abs(c[i]) - 1);
        contrib_counts[a] += static_cast<uint64_t>(s - 1 - i);
      }
    }

    const size_t total_contrib = std::accumulate(contrib_counts.begin(), contrib_counts.end(), 0ull);
    const size_t max_contrib   = *std::max_element(contrib_counts.begin(), contrib_counts.end());
    const size_t user_cap      = std::min(total_contrib, static_cast<size_t>(max_buffer_contributions));
    auto opt = detail::plan(total_contrib, t, user_cap);
    size_t per_thread_buffer = opt.per_thread_buffer;

    bool bumped_to_fit = false;
    if (per_thread_buffer < max_contrib) { per_thread_buffer = max_contrib; bumped_to_fit = true; }
    const size_t target_passes =
        (per_thread_buffer > 0) ? ((total_contrib + per_thread_buffer * t - 1) / (per_thread_buffer * t)) : 0;

    // ---------- Phase 2: partition variables into batches ----------
    std::vector<Batch> batches;
    {
      uint32_t start = 0;
      uint64_t accum = 0;
      for (uint32_t v = 0; v < n; v++)
      {
        const uint64_t cnt = contrib_counts[v];
        if (accum + cnt > static_cast<uint64_t>(per_thread_buffer) && v > start)
        {
          batches.push_back(Batch{start, static_cast<uint32_t>(v - 1)});
          start = v; accum = cnt;
        }
        else accum += cnt;
      }
      if (start < n) batches.push_back(Batch{start, n - 1});
    }

    // Batch stats (also used as a heuristic for reservations).
    std::vector<uint64_t> batch_contrib_sizes;
    batch_contrib_sizes.reserve(batches.size());
    uint64_t batch_contrib_sum = 0, batch_contrib_min = std::numeric_limits<uint64_t>::max(), batch_contrib_max = 0;
    for (const auto &b : batches)
    {
      uint64_t s = 0;
      for (uint32_t v = b.start; v <= b.end; ++v) s += contrib_counts[v];
      batch_contrib_sizes.push_back(s);
      batch_contrib_sum += s;
      batch_contrib_min = std::min(batch_contrib_min, s);
      batch_contrib_max = std::max(batch_contrib_max, s);
    }
    const double batch_contrib_avg = batches.empty() ? 0.0
                                        : static_cast<double>(batch_contrib_sum) / static_cast<double>(batches.size());

    if (std::getenv("VIG_OPT_DEBUG") != nullptr)
    {
      std::cerr << "[vig_opt_plan] batches=" << batches.size()
                << " total_contrib=" << total_contrib
                << " max_buffer_contributions_user=" << max_buffer_contributions
                << " per_thread_buffer=" << per_thread_buffer
                << " bumped_to_fit=" << (bumped_to_fit ? 1 : 0)
                << " target_passes=" << target_passes
                << " batch_contrib_min=" << (batches.empty() ? 0 : batch_contrib_min)
                << " batch_contrib_max=" << (batches.empty() ? 0 : batch_contrib_max)
                << " batch_contrib_avg=" << batch_contrib_avg
                << "\n";
    }

    // ---------- Phase 3: process batches in rounds ----------
    const size_t total_batches = batches.size();
    const size_t rounds = (total_batches + t - 1) / t;

    std::vector<std::vector<Edge>> worker_edges(t);

    // var -> active batch id in current round
    std::vector<int> var_to_active(n, -1);
  // include in transient peak
#if defined(THESIS_VIG_MEMORY_ACCOUNTING)
  detail::g_mem_gauge.add(var_to_active.capacity() * sizeof(int));
#endif

    struct ActiveBatch
    {
      Batch range;
      std::vector<uint32_t> offsets;                      // prefix offsets per variable in batch
      std::vector<uint32_t> counts32;                     // contrib count per variable (narrowed)
      std::unique_ptr<std::atomic<uint32_t>[]> wptrs;     // atomic write pointers per variable
      size_t wptrs_len = 0;
      std::vector<BufferEntry> buffer;                    // flat buffer (b,w)
      size_t tracked_bytes = 0;                           // memory gauge
    };

    // Precompute weights up to the observed maximum (bounded). Avoid huge allocations for tau=inf.
    const size_t w_table_max = (max_clause_size_observed >= 2 ? max_clause_size_observed : 2);
    std::vector<float> w_table(w_table_max + 1, 0.0f);
    for (size_t s = 2; s <= w_table_max; ++s)
      w_table[s] = static_cast<float>(inv_binom2(s));

    // Clause domain per worker
    std::vector<size_t> cbegin(t), cend(t);
    const size_t C = clauses.size();
    for (unsigned tid = 0; tid < t; ++tid) {
      cbegin[tid] = (C * tid) / t;
      cend[tid]   = (C * (tid + 1)) / t;
    }

    std::barrier sync(t);
    std::atomic<size_t> r_idx{0};

    std::vector<ActiveBatch> active;
    size_t batch_count_cur = 0;

    // Track peak of per-thread edge buffers across rounds.
    size_t worker_edges_peak_bytes = 0;

    auto prepare_round = [&](size_t r)
    {
      active.clear();
      const size_t first_batch = r * t;
      batch_count_cur = std::min(static_cast<size_t>(t), total_batches - first_batch);
      active.reserve(batch_count_cur);

      for (size_t bi = 0; bi < batch_count_cur; ++bi)
      {
        const Batch &bch = batches[first_batch + bi];
        ActiveBatch ab;
        ab.range = bch;

        const uint32_t sV = bch.start;
        const uint32_t eV = bch.end;
        if (sV <= eV)
        {
          const size_t len = static_cast<size_t>(eV - sV + 1);
          ab.offsets.assign(len, 0u);
          ab.counts32.assign(len, 0u);

          uint64_t pref64 = 0;
          for (uint32_t a = sV; a <= eV; ++a)
          {
            const size_t idx = static_cast<size_t>(a - sV);
            ab.offsets[idx] = static_cast<uint32_t>(pref64);
            const uint64_t c64 = contrib_counts[a];
            if (c64 > std::numeric_limits<uint32_t>::max())
              throw std::overflow_error("per-variable contribution count exceeds 32-bit range");
            ab.counts32[idx] = static_cast<uint32_t>(c64);
            pref64 += c64;
            var_to_active[a] = static_cast<int>(bi);
          }

          const uint64_t last_off = len ? static_cast<uint64_t>(ab.offsets.back()) : 0ull;
          const uint64_t last_cnt = len ? static_cast<uint64_t>(ab.counts32.back()) : 0ull;
          const uint64_t total_sz64 = last_off + last_cnt;
          if (total_sz64 > static_cast<uint64_t>(std::numeric_limits<size_t>::max()))
            throw std::overflow_error("active batch buffer size exceeds size_t");
          const size_t total_sz = static_cast<size_t>(total_sz64);

          ab.buffer.assign(total_sz, BufferEntry{0u, 0.0f});
          ab.wptrs.reset(new std::atomic<uint32_t>[len]);
          ab.wptrs_len = len;
          for (size_t i = 0; i < len; ++i)
            ab.wptrs[i].store(ab.offsets[i], std::memory_order_relaxed);

          // Accounting
#if defined(THESIS_VIG_MEMORY_ACCOUNTING)
          ab.tracked_bytes += ab.offsets.capacity()  * sizeof(uint32_t);
          ab.tracked_bytes += ab.counts32.capacity() * sizeof(uint32_t);
          ab.tracked_bytes += ab.buffer.capacity()   * sizeof(BufferEntry);
          ab.tracked_bytes += ab.wptrs_len          * sizeof(std::atomic<uint32_t>);
          detail::g_mem_gauge.add(ab.tracked_bytes);
#endif
        }
        active.emplace_back(std::move(ab));
      }
    };

    auto cleanup_round = [&]()
    {
      for (size_t bi = 0; bi < batch_count_cur; ++bi)
      {
    const auto &bch = active[bi].range;
    for (uint32_t a = bch.start; a <= bch.end; ++a) var_to_active[a] = -1;
#if defined(THESIS_VIG_MEMORY_ACCOUNTING)
    detail::g_mem_gauge.sub(active[bi].tracked_bytes);
#endif
      }
      active.clear();
      batch_count_cur = 0;

      // After each round, compute current worker_edges footprint and track peak.
  size_t round_bytes = 0;
  for (auto &ve : worker_edges) round_bytes += ve.capacity() * sizeof(Edge);
#if defined(THESIS_VIG_MEMORY_ACCOUNTING)
  if (round_bytes > worker_edges_peak_bytes) worker_edges_peak_bytes = round_bytes;
#endif
    };

    auto worker = [&](unsigned tid)
    {
      const size_t begin = cbegin[tid];
      const size_t end   = cend[tid];

      for (;;)
      {
        const size_t r = r_idx.load(std::memory_order_acquire);
        if (r >= rounds) break;

        if (tid == 0) prepare_round(r);
        sync.arrive_and_wait(); // active ready

        // ONE-PASS SCAN+FILL with batched atomics.
        for (size_t ci = begin; ci < end; ++ci)
        {
          const auto &c = clauses[ci];
          const size_t s = c.size();
          if (s < 2 || s > clause_size_threshold) continue;

          // s is guaranteed <= clause_size_threshold and we recorded max_clause_size_observed accordingly
          // Ensure index is within table bounds.
          const float w_pair = (s <= w_table_max) ? w_table[s]
                                                  : static_cast<float>(inv_binom2(s));
          for (size_t i = 0; i + 1 < s; ++i)
          {
            const uint32_t u = static_cast<uint32_t>(std::abs(c[i]) - 1);
            const int abi = var_to_active[u];
            if (abi < 0) continue;

            auto &ab = active[static_cast<size_t>(abi)];
            const size_t idx = static_cast<size_t>(u - ab.range.start);

            const uint32_t delta = static_cast<uint32_t>(s - 1 - i);
            const uint32_t pos0  = ab.wptrs[idx].fetch_add(delta, std::memory_order_relaxed);

            uint32_t pos = pos0;
            for (size_t j = i + 1; j < s; ++j)
            {
              const uint32_t b = static_cast<uint32_t>(std::abs(c[j]) - 1);
              ab.buffer[pos++] = BufferEntry{ b, w_pair };
            }
          }
        }

        sync.arrive_and_wait(); // end FILL

        // ACCUM: worker tid reduces batch tid if exists.
        if (tid < batch_count_cur)
        {
          auto &ab = active[tid];
          const uint32_t sV = ab.range.start;
          const uint32_t eV = ab.range.end;

          // Heuristic reservation
          const size_t global_batch_index = r * t + tid;
          if (global_batch_index < batch_contrib_sizes.size())
          {
            auto &edges_out = worker_edges[tid];
            const uint64_t contrib_est = batch_contrib_sizes[global_batch_index];
            edges_out.reserve(edges_out.size() + static_cast<size_t>(contrib_est / 2));
          }

          if (sV <= eV)
          {
            auto &edges_out = worker_edges[tid];
            for (uint32_t a = sV; a <= eV; ++a)
            {
              const size_t idx = static_cast<size_t>(a - sV);
              const uint32_t off = ab.offsets[idx];
              const uint32_t cnt = ab.counts32[idx];
              if (!cnt) continue;

              BufferEntry *first = ab.buffer.data() + off;
              BufferEntry *last  = first + cnt;

              std::sort(first, last, [](const BufferEntry &x, const BufferEntry &y)
                        { return x.b < y.b; });

              uint32_t curr = first->b;
              double sum = 0.0;
              for (BufferEntry *p = first; p != last; ++p)
              {
                if (p->b != curr)
                {
                  edges_out.emplace_back(a, curr, sum);
                  curr = p->b; sum = 0.0;
                }
                sum += static_cast<double>(p->w);
              }
              edges_out.emplace_back(a, curr, sum);
            }
          }
        }

        sync.arrive_and_wait(); // end ACCUM

        if (tid == 0) { cleanup_round(); r_idx.fetch_add(1, std::memory_order_acq_rel); }
        sync.arrive_and_wait(); // next round
      }
    };

    // Launch pool
    std::vector<std::thread> pool;
    pool.reserve(t);
    for (unsigned tid = 0; tid < t; ++tid) pool.emplace_back(worker, tid);
    for (auto &th : pool) th.join();

  // Remove var_to_active from transient gauge now that we're done.
#if defined(THESIS_VIG_MEMORY_ACCOUNTING)
  detail::g_mem_gauge.sub(var_to_active.capacity() * sizeof(int));
#endif

    if (std::getenv("VIG_OPT_DEBUG") != nullptr)
    {
      std::cerr << "[vig_opt_stats] batches=" << batches.size()
                << " rounds=" << rounds
                << " passes_over_clauses=" << rounds  // one pass per round
                << " threads=" << t
                << " total_contrib=" << total_contrib
                << " batch_contrib_min=" << (batches.empty() ? 0 : batch_contrib_min)
                << " batch_contrib_max=" << (batches.empty() ? 0 : batch_contrib_max)
                << " batch_contrib_avg=" << batch_contrib_avg
                << "\n";
    }

    // Merge per-thread edge buffers (note: may temporarily double memory with result.edges)
    size_t total_edges = 0;
    for (const auto &ve : worker_edges) total_edges += ve.size();
    result.edges.reserve(total_edges);
    for (auto &ve : worker_edges)
    {
      result.edges.insert(result.edges.end(),
                          std::make_move_iterator(ve.begin()),
                          std::make_move_iterator(ve.end()));
      std::vector<Edge>().swap(ve);
    }

    if (sort_descending_by_weight)
    {
      std::sort(result.edges.begin(), result.edges.end(),
                [](const Edge &A, const Edge &B)
                {
                  if (A.w != B.w) return A.w > B.w;
                  if (A.u != B.u) return A.u < B.u;
                  return A.v < B.v;
                });
    }

  // ---------------- Memory breakdown & final aggregation_memory ----------------
#if defined(THESIS_VIG_MEMORY_ACCOUNTING)
  const size_t batch_peak_bytes     = detail::g_mem_gauge.peak.load(std::memory_order_relaxed);
  const size_t result_edges_bytes   = result.edges.capacity() * sizeof(Edge);
  const size_t misc_bytes =
    contrib_counts.capacity() * sizeof(uint64_t)
    + batches.capacity()       * sizeof(Batch)
    + w_table.capacity()       * sizeof(float)
    + cbegin.capacity()        * sizeof(size_t)
    + cend.capacity()          * sizeof(size_t);

  if (std::getenv("VIG_OPT_DEBUG") != nullptr)
  {
    std::cerr << "[vig_opt_mem]"
        << " batch_peak="        << batch_peak_bytes
        << " worker_edges_peak=" << worker_edges_peak_bytes
        << " result_edges="      << result_edges_bytes
        << " misc="              << misc_bytes
        << "\n";
  }

  // Publish an actionable aggregate (excludes CNF storage and global program allocations).
  result.aggregation_memory =
    batch_peak_bytes + worker_edges_peak_bytes + result_edges_bytes + misc_bytes;
#else
  result.aggregation_memory = 0;
#endif

    return result;
  }

} // namespace thesis
