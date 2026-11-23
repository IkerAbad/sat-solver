#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "solver.hpp"

namespace sat {

struct GeneratedInstance {
  int nvars = 0;
  std::vector<std::vector<Lit>> clauses;
  std::vector<std::string> comments;
};

GeneratedInstance generateRandom3Sat(int nvars, double ratio, uint64_t seed);
GeneratedInstance generatePigeonhole(int pigeons, int holes);
GeneratedInstance generateColoring(int vertices, int colors, double edge_prob,
                                   uint64_t seed, bool planted);

}  // namespace sat
