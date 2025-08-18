#pragma once

#include <vector>
#include <string>
#include <fstream>
#include <iostream>
#include <cstdlib>   // std::atoi, std::abs
#include <istream>

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

  bool parse_stream(std::istream& file, bool variable_compaction) {
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

    valid = clauses.size() == clause_count;

    if (valid && variable_compaction) {
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
    return valid;
  }

public:
  CNF(std::istream& in, bool variable_compaction = true) {
    parse_stream(in, variable_compaction);
  }

  CNF(const std::string &file_path, bool variable_compaction = true) {
    std::ifstream file(file_path);
    if (!file.is_open()) {
      std::cerr << "Error: Could not open the file!" << std::endl;
      return;
    }
    parse_stream(file, variable_compaction);
  }

  bool is_valid() const { return valid; }
  const std::vector<std::vector<int>> &get_clauses() const { return clauses; }
  unsigned int get_variable_count() const { return variable_count; }
  unsigned int get_clause_count() const { return clause_count; }
};

} // namespace thesis
