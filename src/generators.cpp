#include "generators.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <random>
#include <sstream>
#include <stdexcept>

namespace sat {
namespace {

std::string formatDouble(double value) {
  std::ostringstream out;
  out.precision(6);
  out << value;
  return out.str();
}

int randomInt(std::mt19937_64& rng, int bound) {
  return static_cast<int>(rng() % static_cast<uint64_t>(bound));
}

}  // namespace

GeneratedInstance generateRandom3Sat(int nvars, double ratio, uint64_t seed) {
  if (nvars < 3) {
    throw std::invalid_argument("random 3-SAT needs at least 3 variables");
  }
  if (!(ratio > 0.0) || !std::isfinite(ratio)) {
    throw std::invalid_argument("ratio must be a positive finite number");
  }

  GeneratedInstance instance;
  instance.nvars = nvars;
  instance.comments.push_back("random 3-SAT at ratio " + formatDouble(ratio) +
                              ", seed " + std::to_string(seed));

  const int nclauses = std::max(1, static_cast<int>(std::llround(ratio * nvars)));
  instance.clauses.reserve(static_cast<size_t>(nclauses));

  std::mt19937_64 rng(seed);
  for (int c = 0; c < nclauses; ++c) {
    int a = randomInt(rng, nvars);
    int b = randomInt(rng, nvars - 1);
    if (b >= a) {
      ++b;
    }
    int d = randomInt(rng, nvars - 2);
    if (d >= std::min(a, b)) {
      ++d;
    }
    if (d >= std::max(a, b)) {
      ++d;
    }

    std::vector<Lit> clause;
    clause.reserve(3);
    for (int v : {a, b, d}) {
      clause.push_back(mkLit(v, (rng() & 1) != 0));
    }
    instance.clauses.push_back(std::move(clause));
  }
  return instance;
}

GeneratedInstance generatePigeonhole(int pigeons, int holes) {
  if (pigeons <= 0 || holes <= 0) {
    throw std::invalid_argument("pigeons and holes must be positive");
  }

  GeneratedInstance instance;
  instance.nvars = pigeons * holes;
  instance.comments.push_back("pigeonhole: " + std::to_string(pigeons) + " pigeons, " +
                              std::to_string(holes) + " holes");

  auto variable = [holes](int pigeon, int hole) {
    return pigeon * holes + hole;
  };

  for (int p = 0; p < pigeons; ++p) {
    std::vector<Lit> at_least_one;
    at_least_one.reserve(static_cast<size_t>(holes));
    for (int h = 0; h < holes; ++h) {
      at_least_one.push_back(mkLit(variable(p, h)));
    }
    instance.clauses.push_back(std::move(at_least_one));

    for (int h1 = 0; h1 < holes; ++h1) {
      for (int h2 = h1 + 1; h2 < holes; ++h2) {
        instance.clauses.push_back(
            {mkLit(variable(p, h1), true), mkLit(variable(p, h2), true)});
      }
    }
  }

  for (int h = 0; h < holes; ++h) {
    for (int p1 = 0; p1 < pigeons; ++p1) {
      for (int p2 = p1 + 1; p2 < pigeons; ++p2) {
        instance.clauses.push_back(
            {mkLit(variable(p1, h), true), mkLit(variable(p2, h), true)});
      }
    }
  }
  return instance;
}

GeneratedInstance generateColoring(int vertices, int colors, double edge_prob,
                                   uint64_t seed, bool planted) {
  if (vertices <= 0 || colors <= 0) {
    throw std::invalid_argument("vertices and colors must be positive");
  }
  if (!(edge_prob >= 0.0 && edge_prob <= 1.0)) {
    throw std::invalid_argument("edge probability must be in [0, 1]");
  }

  GeneratedInstance instance;
  instance.nvars = vertices * colors;
  instance.comments.push_back(
      "graph coloring: " + std::to_string(vertices) + " vertices, " +
      std::to_string(colors) + " colors, edge probability " + formatDouble(edge_prob) +
      ", seed " + std::to_string(seed) + (planted ? ", planted" : ", random"));

  auto variable = [colors](int vertex, int color) {
    return vertex * colors + color;
  };

  std::mt19937_64 rng(seed);
  std::vector<int> planted_color(static_cast<size_t>(vertices));
  for (int v = 0; v < vertices; ++v) {
    planted_color[static_cast<size_t>(v)] = randomInt(rng, colors);
  }

  for (int v = 0; v < vertices; ++v) {
    std::vector<Lit> at_least_one;
    at_least_one.reserve(static_cast<size_t>(colors));
    for (int c = 0; c < colors; ++c) {
      at_least_one.push_back(mkLit(variable(v, c)));
    }
    instance.clauses.push_back(std::move(at_least_one));

    for (int c1 = 0; c1 < colors; ++c1) {
      for (int c2 = c1 + 1; c2 < colors; ++c2) {
        instance.clauses.push_back(
            {mkLit(variable(v, c1), true), mkLit(variable(v, c2), true)});
      }
    }
  }

  const uint64_t threshold =
      static_cast<uint64_t>(edge_prob * 1000000.0 + 0.5);  // deterministic roll
  for (int u = 0; u < vertices; ++u) {
    for (int v = u + 1; v < vertices; ++v) {
      if (planted && planted_color[static_cast<size_t>(u)] ==
                         planted_color[static_cast<size_t>(v)]) {
        continue;
      }
      if ((rng() % 1000000ULL) >= threshold) {
        continue;
      }
      for (int c = 0; c < colors; ++c) {
        instance.clauses.push_back(
            {mkLit(variable(u, c), true), mkLit(variable(v, c), true)});
      }
    }
  }
  return instance;
}

}  // namespace sat
