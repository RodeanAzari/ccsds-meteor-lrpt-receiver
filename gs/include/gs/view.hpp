// gs-view's screen, from gs-rx's status snapshot (ADR 0016). Not on the data path: plain strings and maps.
#ifndef GS_VIEW_HPP
#define GS_VIEW_HPP

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <string_view>

namespace gs {

using Status = std::map<std::string, std::string, std::less<>>;

// key=value lines; lines without '=' are ignored.
Status parse_status(std::string_view text);

// A counter's value, if present and a whole number.
std::optional<std::uint64_t> status_u64(const Status& s, std::string_view key);

// The screen as plain text lines (no control codes). `prev`, when given, is the snapshot before `now`; rates
// are taken over their elapsed_ms difference.
std::string render(const Status& now, const Status* prev);

}  // namespace gs

#endif  // GS_VIEW_HPP
