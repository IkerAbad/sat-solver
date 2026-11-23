#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace sat {

enum class HeuristicKind { Vsids, Vmtf, Random };

bool parseHeuristic(const std::string& text, HeuristicKind& out);
const char* heuristicName(HeuristicKind kind);

class DecisionHeuristic {
public:
  virtual ~DecisionHeuristic() = default;

  virtual void assign(int var) = 0;
  virtual void unassign(int var) = 0;
  virtual void bump(int var) = 0;
  virtual void onConflict() {}
  virtual int pick() = 0;
};

std::unique_ptr<DecisionHeuristic> makeDecisionHeuristic(HeuristicKind kind,
                                                        int nvars,
                                                        uint64_t seed);

}  // namespace sat
