#include "thesis/cli.hpp"
#include <charconv>
#include <stdexcept>
#include <sstream>
#include <algorithm>

namespace thesis {

long long parse_int64(const std::string& s, long long minVal, long long maxVal) {
    long long value = 0;
    const char* begin = s.data();
    const char* end = s.data() + s.size();
    auto [ptr, ec] = std::from_chars(begin, end, value);
    if (ec != std::errc{} || ptr != end) {
        throw std::invalid_argument("invalid integer: " + s);
    }
    if (value < minVal || value > maxVal) {
        throw std::out_of_range("value out of range");
    }
    return value;
}

// ---------------- ArgParser ----------------

ArgParser::ArgParser(std::string description) : desc_(std::move(description)) {}

void ArgParser::add_option(const OptionSpec& opt) {
    InternalOpt io{opt, false};
    std::size_t idx = opts_.size();
    opts_.push_back(io);
    indexByLong_[opt.longName] = idx;
    if (opt.shortName) indexByShort_[opt.shortName] = idx;
    if (!opt.defaultValue.empty()) {
        values_[opt.longName] = opt.defaultValue;
    }
}

void ArgParser::add_flag(const std::string& longName, char shortName, const std::string& help) {
    OptionSpec spec;
    spec.longName = longName;
    spec.shortName = shortName;
    spec.type = ArgType::Flag;
    spec.help = help;
    InternalOpt io{spec, true};
    std::size_t idx = opts_.size();
    opts_.push_back(io);
    indexByLong_[spec.longName] = idx;
    if (shortName) indexByShort_[shortName] = idx;
    // flags default to false unless provided
}

const ArgParser::InternalOpt* ArgParser::find_long(const std::string& name) const {
    auto it = indexByLong_.find(name);
    if (it == indexByLong_.end()) return nullptr;
    return &opts_[it->second];
}

const ArgParser::InternalOpt* ArgParser::find_short(char c) const {
    auto it = indexByShort_.find(c);
    if (it == indexByShort_.end()) return nullptr;
    return &opts_[it->second];
}

static inline bool iequals(const std::string& a, const std::string& b) {
    if (a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); ++i) {
        if (std::tolower(static_cast<unsigned char>(a[i])) != std::tolower(static_cast<unsigned char>(b[i]))) return false;
    }
    return true;
}

bool ArgParser::parse(int argc, char** argv) {
    helpRequested_ = false;
    // Add implicit help flags if not already present
    if (!find_long("help")) {
        add_flag("help", 'h', "Show this help message and exit");
    }

    for (int i = 1; i < argc; ++i) {
        std::string tok = argv[i];
        if (tok.rfind("--", 0) == 0) {
            std::string name = tok.substr(2);
            if (name.empty()) throw std::runtime_error("invalid option '--'");
            const InternalOpt* io = find_long(name);
            if (!io) throw std::runtime_error("unknown option '--" + name + "'");
            if (io->spec.type == ArgType::Flag) {
                present_[io->spec.longName] = true;
                if (name == "help") helpRequested_ = true;
            } else {
                if (i + 1 >= argc) throw std::runtime_error("missing value for --" + name);
                std::string val = argv[++i];
                values_[io->spec.longName] = val;
                present_[io->spec.longName] = true;
            }
        } else if (tok.rfind('-', 0) == 0 && tok.size() >= 2) {
            // Short option handling. We intentionally do NOT support single-dash
            // long options or short-option bundling. Reject tokens like "-foo" or
            // "-abc" to avoid ambiguity; require "--foo" for long options.
            if (tok.size() > 2) {
                throw std::runtime_error(std::string("invalid short option or cluster: ") + tok +
                                         ". Use --<long> for long options.");
            }
            char c = tok[1];
            const InternalOpt* io = find_short(c);
            if (!io) throw std::runtime_error(std::string("unknown option '-") + c + "'");
            if (io->spec.type == ArgType::Flag) {
                present_[io->spec.longName] = true;
                if (c == 'h') helpRequested_ = true;
            } else {
                if (i + 1 >= argc) throw std::runtime_error(std::string("missing value for -") + c);
                std::string val = argv[++i];
                values_[io->spec.longName] = val;
                present_[io->spec.longName] = true;
            }
        } else {
            throw std::runtime_error("unexpected positional argument: " + tok);
        }
    }

    // Validate required options
    for (const auto& io : opts_) {
        if (io.spec.required && !present_[io.spec.longName] && io.spec.defaultValue.empty()) {
            throw std::runtime_error("missing required option --" + io.spec.longName);
        }
    }

    return !helpRequested_;
}

bool ArgParser::provided(const std::string& longName) const {
    auto it = present_.find(longName);
    return it != present_.end() && it->second;
}

std::string ArgParser::get_string(const std::string& longName) const {
    auto it = values_.find(longName);
    if (it != values_.end()) return it->second;
    // Find default
    auto iit = indexByLong_.find(longName);
    if (iit != indexByLong_.end()) {
        const auto& spec = opts_[iit->second].spec;
        if (!spec.defaultValue.empty()) return spec.defaultValue;
    }
    throw std::runtime_error("option --" + longName + " not provided");
}

long long ArgParser::get_int64(const std::string& longName) const {
    std::string s = get_string(longName);
    const auto& spec = opts_[indexByLong_.at(longName)].spec;
    return parse_int64(s, std::numeric_limits<long long>::min(), std::numeric_limits<long long>::max());
}

unsigned long long ArgParser::get_uint64(const std::string& longName) const {
    const auto& spec = opts_[indexByLong_.at(longName)].spec;
    auto it = values_.find(longName);
    std::string s = (it != values_.end()) ? it->second : spec.defaultValue;
    if (s.empty()) throw std::runtime_error("option --" + longName + " not provided");
    if (spec.allowInfToken && (iequals(s, "inf") || iequals(s, "INF"))) {
        return std::numeric_limits<unsigned long long>::max();
    }
    unsigned long long value = 0;
    const char* begin = s.data();
    const char* end = s.data() + s.size();
    auto [ptr, ec] = std::from_chars(begin, end, value);
    if (ec != std::errc{} || ptr != end) throw std::invalid_argument("invalid integer: " + s);
    return value;
}

std::size_t ArgParser::get_size(const std::string& longName) const {
    const auto& spec = opts_[indexByLong_.at(longName)].spec;
    auto it = values_.find(longName);
    std::string s = (it != values_.end()) ? it->second : spec.defaultValue;
    if (s.empty()) throw std::runtime_error("option --" + longName + " not provided");
    if (spec.allowInfToken && (iequals(s, "inf") || iequals(s, "INF"))) {
        return std::numeric_limits<std::size_t>::max();
    }
    unsigned long long value = 0;
    const char* begin = s.data();
    const char* end = s.data() + s.size();
    auto [ptr, ec] = std::from_chars(begin, end, value);
    if (ec != std::errc{} || ptr != end) throw std::invalid_argument("invalid size: " + s);
    return static_cast<std::size_t>(value);
}

bool ArgParser::get_flag(const std::string& longName) const {
    auto it = present_.find(longName);
    return it != present_.end() && it->second;
}

std::string ArgParser::usage(const std::string& progName) const {
    std::ostringstream oss;
    oss << "Usage: " << progName << " ";
    for (const auto& io : opts_) {
        if (io.spec.longName == "help") continue; // implicit
        oss << (io.spec.required ? "" : "[");
    if (io.spec.shortName) oss << "-" << io.spec.shortName << "|";
    oss << "--" << io.spec.longName;
        if (io.spec.type != ArgType::Flag) {
            oss << " " << (io.spec.valueName.empty() ? "VAL" : io.spec.valueName);
        }
        oss << (io.spec.required ? " " : "] ");
    }
    return oss.str();
}

std::string ArgParser::help(const std::string& progName) const {
    std::ostringstream oss;
    if (!desc_.empty()) oss << desc_ << "\n";
    oss << usage(progName) << "\n\nOptions:\n";
    oss << "  Note: short options use a single dash and one letter (e.g., -i).\n";
    oss << "        long options require two dashes (e.g., --input).\n";
    oss << "        Single-dash multi-letter tokens like '-input' are not accepted.\n";
    for (const auto& io : opts_) {
        if (io.spec.longName == "help") continue; // show help last
        oss << "  ";
        if (io.spec.shortName) oss << "-" << io.spec.shortName << ", "; else oss << "    ";
        oss << "--" << io.spec.longName;
        if (io.spec.type != ArgType::Flag) {
            oss << " " << (io.spec.valueName.empty() ? "VAL" : io.spec.valueName);
        }
        if (!io.spec.help.empty()) oss << "\n      " << io.spec.help;
        if (!io.spec.defaultValue.empty()) oss << " (default: " << io.spec.defaultValue << ")";
        if (io.spec.required) oss << " [required]";
        oss << "\n";
    }
    // show implicit help
    oss << "  -h, --help\n      Show this help message and exit\n";
    return oss.str();
}

} // namespace thesis
