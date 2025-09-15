# VIG Clause-Size Weighting: Design & Patch

This document explains **what the provided `vig.cpp` code currently does**, **what behavior we want**, and **exactly how to change the code** to achieve it.

---

## 1) What the current code does

### 1.1 Variable Incidence Graph (VIG) builders

- There are two VIG builders in `namespace thesis`:
  - `build_vig_naive`: single-threaded, aggregates undirected edges `(u,v)` with weights using a hash map.
  - `build_vig_optimized`: multi-threaded, memory-aware batching. It:
    1) Computes per-variable contribution counts.
    2) Partitions variables into batches under a memory budget.
    3) Scans clauses **once per round** and writes neighbor entries into a flat buffer with few atomics.
    4) Locally sorts/reduces each variable's neighbors to produce weighted edges.

- **Pair weight** currently depends only on clause size `s`:
  - `w(s) = 2 / (s * (s - 1)) = 1 / C(s, 2)`
  - Result: each clause contributes total mass `1` (because it has `C(s,2)` pairs). Smaller clauses give each pair **more** weight than larger clauses, but **every clause contributes the same total** regardless of size.

- Clauses with size `< 2` or `> clause_size_threshold` (call it **τ**) are **skipped**. So currently **only** sizes `2 ≤ s ≤ τ` are counted.

- Weights are used in:
  - `build_vig_naive` (directly during pair aggregation),
  - `build_vig_optimized` (during the one-pass fill of per-variable buffers),
  - `Louvain::build_graph` (to build a directed CSR version with both directions stored).

### 1.2 Canonicalization and normalization assumptions

- Clauses are **pre-normalized** by the CNF parser (sorted by `|lit|`, deduplicated, no tautologies). Iterating pairs with `i < j` yields canonical `(u < v)` pairs with no duplicates.

---

## 2) What behavior we want (the “why”)

We want a **single, global exponent α** that **penalizes large clauses more strongly** than the current `1/s` effect — i.e., **smaller clauses contribute more**. In addition, we use a **cutoff τ** (same `clause_size_threshold` as in the code) and want discarding clauses with sizes **> τ** to have **negligible** impact on downstream processing.

Concretely, we want to choose **α** so that **even at the cutoff size `s = τ`**, a clause's total mass is at most an **ε** fraction of a binary clause's total mass. This conservative bound ensures **all** clauses with `s ≥ τ` are tiny, so ignoring sizes `> τ` is mathematically harmless.

---

## 3) The change (design)

### 3.1 Parameterized weight (Mode A: no dataset histogram)

Replace the fixed pair weight with a **power-law family** controlled by α:

\[
w_\alpha(s) \;=\; \frac{2 \, s^{-\alpha}}{s-1} \quad (s \ge 2).
\]

- When `α = 1`, this **exactly reproduces** the current behavior (`2/(s(s-1))`).
- `α > 1` **increases** small-clause influence and **suppresses** large clauses.

For a size-`s` clause, the **total** clause mass becomes:

\[
T_\alpha(s) \;=\; \binom{s}{2}\, w_\alpha(s) \;=\; s^{\,1-\alpha}.
\]

### 3.2 Choosing α from (τ, ε) only (no histogram)

To make the τ-cutoff harmless **without** looking at the instance's size distribution, enforce that a clause at the boundary has tiny total mass compared to a binary clause:

\[
\frac{T_\alpha(\tau)}{T_\alpha(2)} \;=\; \Big(\frac{\tau}{2}\Big)^{1-\alpha} \;\le\; \varepsilon.
\]

Solving for α:

\[
\boxed{\;\alpha \;\ge\; 1 \;-\; \frac{\ln \varepsilon}{\ln(\tau/2)}\;}\quad\text{and clamp to }\alpha \ge 1.
\]

Notes:

- If τ ≤ 2 (no meaningful tail), just use `α = 1` (current behavior).
- If τ is “infinite” (i.e., you keep all clauses), pick any `α ≥ 1` reflecting your desired bias toward small clauses (e.g., `α = 1.5`).

---

## 4) How to implement (minimal, explicit patch)

### 4.1 Add a small weighting policy and an α picker

Place these in a suitable header or near the top of `vig.cpp` (above the builders).

```cpp
// --- New: weighting policy and τ-only α picker ---
struct Weighting {
  double alpha = 1.0; // α=1 reproduces current behavior
  inline double pair_weight(size_t s) const {
    if (s < 2) return 0.0;
    return 2.0 * std::pow(double(s), -alpha) / double(s - 1);
  }
};

inline double pick_alpha_tau_only(unsigned tau, double eps) {
  if (tau <= 2) return 1.0; // no meaningful tail to suppress
  double a = 1.0 - std::log(eps) / std::log(double(tau) / 2.0);
  return std::max(1.0, a);
}
```

### 4.2 Precompute weights in the optimized builder

In `build_vig_optimized(...)`, replace the current `inv_binom2` table with the new policy. You can add an overload that accepts a `Weighting` to keep the existing API intact.

**Before:**

```cpp
// Precompute weights up to the observed maximum
const size_t w_table_max = (max_clause_size_observed >= 2 ? max_clause_size_observed : 2);
std::vector<float> w_table(w_table_max + 1, 0.0f);
for (size_t s = 2; s <= w_table_max; ++s)
  w_table[s] = static_cast<float>(inv_binom2(s));
```

**After:**

```cpp
// New: pass in Weighting weighting (with chosen α)
const size_t w_table_max = (max_clause_size_observed >= 2 ? max_clause_size_observed : 2);
std::vector<float> w_table(w_table_max + 1, 0.0f);
for (size_t s = 2; s <= w_table_max; ++s)
  w_table[s] = static_cast<float>(weighting.pair_weight(s));
```

And in the worker loop, replace:

```cpp
const float w_pair = (s <= w_table_max) ? w_table[s]
                                        : static_cast<float>(inv_binom2(s));
```

with:

```cpp
const float w_pair = (s <= w_table_max)
                       ? w_table[s]
                       : static_cast<float>(weighting.pair_weight(s));
```

> **API option A (recommended):** add an overload
>
> ```cpp
> VIG build_vig_optimized(const CNF& cnf,
>                         unsigned clause_size_threshold,
>                         std::size_t max_buffer_contributions,
>                         unsigned num_threads,
>                         const Weighting& weighting);
> 
> // Keep the existing signature by forwarding with α computed from (τ, ε)
> VIG build_vig_optimized(const CNF& cnf,
>                         unsigned clause_size_threshold,
>                         std::size_t max_buffer_contributions,
>                         unsigned num_threads) {
>   Weighting W;
>   // Example ε; make it a parameter if you prefer
>   double eps = 1e-3;
>   W.alpha = pick_alpha_tau_only(clause_size_threshold, eps);
>   return build_vig_optimized(cnf, clause_size_threshold, max_buffer_contributions, num_threads, W);
> }
> ```

### 4.3 Update the naive builder similarly

Replace occurrences of `inv_binom2(s)` with `weighting.pair_weight(s)` and add a forwarding overload.

**Before:**

```cpp
const double w_pair = inv_binom2(s);
```

**After:**

```cpp
const double w_pair = weighting.pair_weight(s);
```

**Overloads:**

```cpp
VIG build_vig_naive(const CNF& cnf,
                    unsigned clause_size_threshold,
                    const Weighting& weighting);

VIG build_vig_naive(const CNF& cnf,
                    unsigned clause_size_threshold) {
  Weighting W; double eps = 1e-3;
  W.alpha = pick_alpha_tau_only(clause_size_threshold, eps);
  return build_vig_naive(cnf, clause_size_threshold, W);
}
```

### 4.4 No changes to memory planning or batching

All batching and memory accounting logic in the optimized path depends on **counts of neighbor writes**, not the numeric weight values. Therefore, **no changes** are needed there.

---

## 5) Usage examples

### 5.1 Use the default (α derived from τ, ε = 1e-3)

```cpp
// τ is your existing clause_size_threshold
auto vig = thesis::build_vig_optimized(cnf, /*tau=*/tau, /*maxbuf=*/MB, /*threads=*/T);
// Or naive:
auto vig2 = thesis::build_vig_naive(cnf, tau);
// Louvain graph:
auto g = Louvain::build_graph(cnf, tau);
```

### 5.2 Explicitly set α (override the default)

```cpp
Weighting W;
W.alpha = 1.5; // stronger bias to small clauses than α=1
auto vig = thesis::build_vig_optimized(cnf, tau, MB, T, W);
auto g = Louvain::build_graph(cnf, tau, W);
```

### 5.3 Pick α from (τ, ε) explicitly

```cpp
double eps = 1e-4;
Weighting W;
W.alpha = pick_alpha_tau_only(tau, eps);
auto vig = thesis::build_vig_optimized(cnf, tau, MB, T, W);
```

---

## 6) Edge cases & notes

- **τ ≤ 2**: No meaningful tail → use `α = 1` (identical to current behavior).  
- **τ = ∞** (keep all clauses): Choose any `α ≥ 1` to tune your bias toward small clauses; there is no cut to suppress.
- **Numeric range**: With large `α` and moderate/large `s`, weights can become very small; if you're storing in `float`, you may clamp to `≥ std::numeric_limits<float>::min()` if desired.
- **Determinism**: All changes preserve the deterministic ordering/aggregation semantics already present.
- **Backwards compatibility**: By adding overloads that **forward** to the new versions, existing call sites continue to work with `α` automatically set from `(τ, ε=1e-3)`.

---

## 7) One-paragraph summary

The original code builds VIGs from CNF with pair weights `2/(s(s-1))`, making each clause contribute the same total mass regardless of size. We introduce a parameterized weight `w_α(s) = 2*s^(-α)/(s-1)` with a single global exponent `α ≥ 1`; `α = 1` reproduces the old behavior, `α > 1` boosts small clauses. To ensure the clause-size cutoff `τ` is harmless, we choose `α` so a size-τ clause's total mass is at most an ε-fraction of a binary clause: `α ≥ 1 - ln(ε)/ln(τ/2)`. We implement this by adding a tiny `Weighting` policy, precomputing a weight table in the optimized builder, and replacing occurrences of `inv_binom2(s)` in all builders (`naive`, `optimized`, and `Louvain`) with `weighting.pair_weight(s)`. No changes are needed to batching/memory planning.
