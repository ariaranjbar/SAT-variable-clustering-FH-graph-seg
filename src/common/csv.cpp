#include "thesis/csv.hpp"

namespace thesis {

CSVWriter::CSVWriter(const std::string& filePath, bool fixedFloat, int precision)
    : fixedFloat_(fixedFloat), precision_(precision) {
    ofs_.open(filePath, std::ios::out | std::ios::trunc);
    if (ofs_) {
        if (fixedFloat_) ofs_.setf(std::ios::fixed, std::ios::floatfield);
        ofs_ << std::setprecision(precision_);
    }
}

CSVWriter::~CSVWriter() { if (ofs_) ofs_.flush(); }

void CSVWriter::close() { if (ofs_) { ofs_.flush(); ofs_.close(); } }

bool CSVWriter::needs_quoting(std::string_view s) {
    for (char c : s) {
        if (c == ',' || c == '"' || c == '\n' || c == '\r') return true;
    }
    if (!s.empty() && (s.front() == ' ' || s.back() == ' ')) return true;
    return false;
}

std::string CSVWriter::escape_cell(std::string_view s) {
    if (!needs_quoting(s)) return std::string(s);
    std::string out; out.reserve(s.size() + 2);
    out.push_back('"');
    for (char c : s) {
        if (c == '"') out.push_back('"');
        out.push_back(c);
    }
    out.push_back('"');
    return out;
}

void CSVWriter::header(const std::vector<std::string>& cols) {
    if (!ofs_) return;
    for (size_t i = 0; i < cols.size(); ++i) {
        if (i) ofs_ << ',';
        ofs_ << escape_cell(cols[i]);
    }
    ofs_ << '\n';
}

void CSVWriter::row(const std::vector<std::string>& cells) {
    if (!ofs_) return;
    for (size_t i = 0; i < cells.size(); ++i) {
        if (i) ofs_ << ',';
        ofs_ << escape_cell(cells[i]);
    }
    ofs_ << '\n';
}

} // namespace thesis
