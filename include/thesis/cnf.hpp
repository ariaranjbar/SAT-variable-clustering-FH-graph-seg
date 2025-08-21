#pragma once

#include <vector>
#include <string>
#include <fstream>
#include <iostream>
#include <cstdlib>   // std::atoi, std::abs
#include <istream>
#include <algorithm>

namespace thesis {

// Parses a DIMACS CNF file and loads its clauses.
// Optional variable compaction remaps variable indices to a dense range [1..k].
class CNF {
private:
  bool valid = false;
  unsigned int variable_count = 0;
  unsigned int clause_count = 0;
  std::vector<std::vector<int>> clauses;
  
  void reset() {
    valid = false;
    variable_count = 0;
    clause_count = 0;
    clauses.clear();
  }

  // Internal: perform variable compaction on current clauses/data.
  void do_compact_variables() {
    // Remap variable indices to a dense range starting at 1, preserving sign.
    std::vector<int> variable_map(variable_count, 0);
    unsigned int current_renamed_variable = 1;
    for (size_t c_idx = 0; c_idx < clauses.size(); c_idx++) {
      auto &clause = clauses[c_idx];
      for (size_t l_idx = 0; l_idx < clause.size(); l_idx++) {
        int literal = clause[l_idx];
        unsigned int var_idx = static_cast<unsigned int>(std::abs(literal)) - 1;
        if (var_idx >= variable_map.size()) {
          // Extend map if the file declared fewer variables than used
          variable_map.resize(var_idx + 1, 0);
        }
        if (variable_map[var_idx] == 0) {
          variable_map[var_idx] = current_renamed_variable++;
        }
        int literal_sign = (literal < 0) ? -1 : 1;
        clause[l_idx] = literal_sign * variable_map[var_idx];
      }
    }
    variable_count = current_renamed_variable - 1;
  }

  // Internal: normalize clauses (sort by abs(var), dedup, drop tautologies/empties) and
  // update clause_count accordingly.
  void do_normalize_clauses() {
    std::vector<std::vector<int>> normalized;
    normalized.reserve(clauses.size());

    for (auto &clause : clauses) {
      if (clause.empty()) continue; // Skip empty

      std::sort(clause.begin(), clause.end(), [](int a, int b) {
        int aa = std::abs(a), bb = std::abs(b);
        if (aa != bb) return aa < bb;
        return a < b; // tie-break for deterministic order
      });

      std::vector<int> out;
      out.reserve(clause.size());
      bool taut = false;

      int prev_abs = 0;
      int prev_sign = 0;
      bool has_prev = false;
      for (int lit : clause) {
        const int a = std::abs(lit);
        const int s = (lit < 0) ? -1 : 1;
        if (has_prev && a == prev_abs) {
          if (s != prev_sign) { taut = true; break; } // literal and its negation present
          // duplicate with same sign, skip
          continue;
        }
        // new variable (by abs)
        out.push_back(lit);
        prev_abs = a; prev_sign = s; has_prev = true;
      }

      if (!taut && !out.empty()) {
        normalized.push_back(std::move(out));
      }
    }

    clauses.swap(normalized);
    clause_count = static_cast<unsigned int>(clauses.size());
  }

  bool parse_stream(std::istream& file, bool variable_compaction, bool normalize) {
    reset();

    std::string line;

    // Skip comment lines (starting with 'c') and blank lines
    while (std::getline(file, line)) {
      if (!line.empty() && line[0] != 'c')
        break;
    }

    // Parse the 'p cnf' line
    if (!line.empty() && line[0] == 'p') {
      const char *str = line.c_str();
      while (*str && (*str != ' ')) ++str; // Skip 'p'
      if (*str == ' ') ++str;              // Skip space
      while (*str && (*str != ' ')) ++str; // Skip 'cnf'
      variable_count = std::atoi(++str);
      while (*str && (*str != ' ')) ++str; // Skip to clause count
      clause_count = std::atoi(++str);

      clauses.reserve(clause_count);
    } else {
      std::cerr << "Error: No valid problem line (starting with 'p') found." << std::endl;
      return false;
    }

    // Read and parse the clauses
    while (std::getline(file, line)) {
      if (line.empty()) continue;
      const char *str = line.c_str();
      if (*str == 'c') continue; // comment line

      while (*str && *str == ' ') { // Skip possible initial whitespace
        ++str;
      }

      const char *str_cursor = str;
      std::vector<int> clause;
      size_t clause_length = 0;

      // First pass: count literals to reserve
      while (*str_cursor) {
        if (*str_cursor == '0') break;
        ++clause_length;
        while (*str_cursor && *str_cursor != ' ') ++str_cursor; // end of label
        while (*str_cursor && *str_cursor == ' ') ++str_cursor; // next label
      }

      str_cursor = str;
      clause.reserve(clause_length);

      // Second pass: parse literals
      while (*str_cursor) {
        if (*str_cursor == '0') break; // Clause end
        int literal = std::atoi(str_cursor);
        clause.push_back(literal);
        while (*str_cursor && *str_cursor != ' ') ++str_cursor; // end of label
        while (*str_cursor && *str_cursor == ' ') ++str_cursor; // next label
      }

      if (!clause.empty()) {
        clauses.push_back(std::move(clause));
      }
    }

    // Perform optional variable compaction first
    valid = true; // We'll normalize and set clause_count to actual retained clauses

    if (variable_compaction) {
      do_compact_variables();
    }

    // Normalize all clauses and update clause_count if requested
    if (valid && normalize) {
      do_normalize_clauses();
    }
    return valid;
  }

public:
  CNF(std::istream& in, bool variable_compaction = true, bool normalize = true) {
    parse_stream(in, variable_compaction, normalize);
  }

  CNF(const std::string &file_path, bool variable_compaction = true, bool normalize = true) {
    std::ifstream file(file_path);
    if (!file.is_open()) {
      std::cerr << "Error: Could not open the file!" << std::endl;
      return;
    }
    parse_stream(file, variable_compaction, normalize);
  }

  bool is_valid() const { return valid; }
  const std::vector<std::vector<int>> &get_clauses() const { return clauses; }
  unsigned int get_variable_count() const { return variable_count; }
  unsigned int get_clause_count() const { return clause_count; }

  // Public API: perform variable compaction on the current CNF.
  // Maintains backward compatibility: constructors already call this when requested.
  // Idempotent: calling multiple times leaves the CNF in a compacted state.
  void compact_variables() {
    if (!valid) return;
    do_compact_variables();
  }

  // Public API: normalize clauses (sort, deduplicate, drop tautologies/empties).
  // Updates clause_count to the number of retained clauses.
  // Idempotent: calling multiple times has no further effect.
  void normalize_clauses() {
    if (!valid) return;
    do_normalize_clauses();
  }
};

} // namespace thesis
