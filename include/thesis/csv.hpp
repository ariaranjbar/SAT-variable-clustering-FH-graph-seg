#pragma once

#include <fstream>
#include <initializer_list>
#include <ios>
#include <iomanip>
#include <sstream>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

namespace thesis {

// Lightweight CSV writer with basic quoting and numeric formatting.
class CSVWriter {
public:
    // If fixedFloat is true, floating point values are written with fixed and the given precision.
    // Otherwise default stream formatting is used.
    explicit CSVWriter(const std::string& filePath, bool fixedFloat = true, int precision = 17);
    ~CSVWriter();

    bool is_open() const { return static_cast<bool>(ofs_); }
    void close();

    // Write header from a list of column names.
    void header(const std::vector<std::string>& cols);
    void header(std::initializer_list<std::string> cols) { header(std::vector<std::string>(cols)); }

    // Write a row from pre-formatted string cells.
    void row(const std::vector<std::string>& cells);

    // Convenience variadic row/header with automatic formatting.
    template <typename... Ts>
    void row(const Ts&... values) {
        std::vector<std::string> cells;
        cells.reserve(sizeof...(Ts));
        (cells.emplace_back(to_string(values)), ...);
        row(cells);
    }

    template <typename... Ts>
    void header(const Ts&... names) {
        std::vector<std::string> cols;
        cols.reserve(sizeof...(Ts));
        (cols.emplace_back(std::string(names)), ...);
        header(cols);
    }

private:
    std::ofstream ofs_{};
    bool fixedFloat_ = true;
    int precision_ = 17;

    static bool needs_quoting(std::string_view s);
    static std::string escape_cell(std::string_view s);

    template <typename T>
    std::string to_string(const T& v) const {
        if constexpr (std::is_same_v<T, std::string>) {
            return v;
        } else if constexpr (std::is_same_v<T, const char*>) {
            return std::string(v);
        } else if constexpr (std::is_same_v<T, char*>) {
            return std::string(v);
        } else if constexpr (std::is_floating_point_v<T>) {
            std::ostringstream oss;
            if (fixedFloat_) oss.setf(std::ios::fixed, std::ios::floatfield);
            oss << std::setprecision(precision_) << v;
            return std::move(oss).str();
        } else {
            std::ostringstream oss;
            oss << v;
            return std::move(oss).str();
        }
    }
};

} // namespace thesis
