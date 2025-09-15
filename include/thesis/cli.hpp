#pragma once
#include <cstddef>
#include <string>
#include <vector>
#include <unordered_map>
#include <limits>

namespace thesis {

// Utility to parse an integer from a string with bounds checking.
// Throws std::invalid_argument or std::out_of_range on error.
long long parse_int64(const std::string& s, long long minVal, long long maxVal);

// Lightweight, reusable CLI parser for small executables.
// Supports long/short options, flags, defaults, required args, and auto help/usage text.
enum class ArgType { Flag, String, Int64, UInt64, Size };

struct OptionSpec {
	std::string longName;        // e.g. "input"
	char shortName = '\0';       // e.g. 'i' (optional)
	ArgType type = ArgType::String;
	std::string valueName;       // e.g. "FILE" or "N"; empty for flags
	std::string help;            // description for --help
	bool required = false;       // must be provided by user
	std::string defaultValue;    // default string (empty means no default)
	bool allowInfToken = false;  // if true for unsigned/size types, accept "inf"/"INF" as max
};

class ArgParser {
public:
	explicit ArgParser(std::string description = "");

	// Add an option (value-bearing) or a flag.
	void add_option(const OptionSpec& opt);
	void add_flag(const std::string& longName, char shortName, const std::string& help);

	// Parse argc/argv. Returns false if --help/-h was requested (help text can be shown).
	// Throws std::runtime_error on invalid input.
	bool parse(int argc, char** argv);

	// Query whether an option (by long name) was explicitly provided by the user.
	bool provided(const std::string& longName) const;

	// Typed accessors. For missing values, returns default or throws if required and missing.
	std::string get_string(const std::string& longName) const;
	long long get_int64(const std::string& longName) const;
	unsigned long long get_uint64(const std::string& longName) const;
	std::size_t get_size(const std::string& longName) const;
	bool get_flag(const std::string& longName) const;

	// Usage/help renderers.
	std::string usage(const std::string& progName) const;
	std::string help(const std::string& progName) const;

private:
	struct InternalOpt {
		OptionSpec spec;
		bool isFlag = false;
	};

	std::string desc_;
	std::vector<InternalOpt> opts_;
	std::unordered_map<std::string, std::size_t> indexByLong_;
	std::unordered_map<char, std::size_t> indexByShort_;
	std::unordered_map<std::string, std::string> values_; // longName -> value string
	std::unordered_map<std::string, bool> present_;       // longName -> provided by user
	bool helpRequested_ = false;

	const InternalOpt* find_long(const std::string& name) const;
	const InternalOpt* find_short(char c) const;
};

} // namespace thesis
