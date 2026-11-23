#pragma once

#include <string>
#include <vector>

#include "solver.hpp"

namespace sat {

struct Formula {
  int nvars = 0;
  std::vector<std::vector<Lit>> clauses;
};

bool parseDimacs(const std::string& path, Formula& formula, std::string& error);

bool writeDimacs(const std::string& path, const Formula& formula,
                 const std::vector<std::string>& comments, std::string& error);

}  // namespace sat
