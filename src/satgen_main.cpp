#include <exception>
#include <iostream>
#include <stdexcept>
#include <string>

#include "dimacs.hpp"
#include "generators.hpp"

namespace {

void printUsage(const char* program) {
  std::cout
      << "Usage: " << program << " <type> [options] --out <file.cnf>\n\n"
      << "Types:\n"
      << "  random3    --vars N [--ratio R] [--seed S]\n"
      << "  php        --pigeons N --holes N\n"
      << "  coloring   --vertices N --colors N [--edge-prob P] [--seed S] [--planted]\n\n"
      << "Options:\n"
      << "  --out FILE       output DIMACS file (required)\n"
      << "  --vars N         number of variables for random 3-SAT\n"
      << "  --ratio R        clauses per variable (default: 4.26)\n"
      << "  --seed S         random seed\n"
      << "  --pigeons N      number of pigeons\n"
      << "  --holes N        number of holes\n"
      << "  --vertices N     number of graph vertices\n"
      << "  --colors N       number of colors\n"
      << "  --edge-prob P    edge probability (default: 0.5)\n"
      << "  --planted        build a graph that is colorable by construction\n";
}

int parseInt(const std::string& text, const std::string& option) {
  size_t consumed = 0;
  long long value = 0;
  try {
    value = std::stoll(text, &consumed, 10);
  } catch (const std::exception&) {
    throw std::runtime_error("invalid value for " + option + ": " + text);
  }
  if (consumed != text.size() || value < 0 || value > 100000000LL) {
    throw std::runtime_error("invalid value for " + option + ": " + text);
  }
  return static_cast<int>(value);
}

double parseDouble(const std::string& text, const std::string& option) {
  size_t consumed = 0;
  double value = 0.0;
  try {
    value = std::stod(text, &consumed);
  } catch (const std::exception&) {
    throw std::runtime_error("invalid value for " + option + ": " + text);
  }
  if (consumed != text.size()) {
    throw std::runtime_error("invalid value for " + option + ": " + text);
  }
  return value;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    printUsage(argv[0]);
    return 1;
  }
  std::string type = argv[1];
  if (type == "--help" || type == "-h" || type == "help") {
    printUsage(argv[0]);
    return 0;
  }

  int vars = 0;
  double ratio = 4.26;
  unsigned long long seed = 1;
  int pigeons = 0;
  int holes = 0;
  int vertices = 0;
  int colors = 0;
  double edge_prob = 0.5;
  bool planted = false;
  std::string out_path;

  try {
    for (int i = 2; i < argc; ++i) {
      std::string arg = argv[i];
      if (arg == "--planted") {
        planted = true;
        continue;
      }
      if (arg.rfind("--", 0) != 0) {
        throw std::runtime_error("unexpected argument: " + arg);
      }
      std::string key = arg;
      std::string value;
      size_t equal = arg.find('=');
      if (equal != std::string::npos) {
        key = arg.substr(0, equal);
        value = arg.substr(equal + 1);
      }
      auto takeValue = [&]() {
        if (!value.empty()) {
          return value;
        }
        if (i + 1 >= argc) {
          throw std::runtime_error("missing value for " + key);
        }
        return std::string(argv[++i]);
      };

      if (key == "--out") {
        out_path = takeValue();
      } else if (key == "--vars") {
        vars = parseInt(takeValue(), key);
      } else if (key == "--ratio") {
        ratio = parseDouble(takeValue(), key);
      } else if (key == "--seed") {
        seed = std::stoull(takeValue());
      } else if (key == "--pigeons") {
        pigeons = parseInt(takeValue(), key);
      } else if (key == "--holes") {
        holes = parseInt(takeValue(), key);
      } else if (key == "--vertices") {
        vertices = parseInt(takeValue(), key);
      } else if (key == "--colors") {
        colors = parseInt(takeValue(), key);
      } else if (key == "--edge-prob") {
        edge_prob = parseDouble(takeValue(), key);
      } else {
        throw std::runtime_error("unknown option: " + key);
      }
    }

    if (out_path.empty()) {
      throw std::runtime_error("--out is required");
    }
  } catch (const std::exception& ex) {
    std::cerr << "error: " << ex.what() << '\n';
    return 1;
  }

  try {
    sat::GeneratedInstance generated;
    if (type == "random3") {
      generated = sat::generateRandom3Sat(vars, ratio, seed);
    } else if (type == "php") {
      generated = sat::generatePigeonhole(pigeons, holes);
    } else if (type == "coloring") {
      generated = sat::generateColoring(vertices, colors, edge_prob, seed, planted);
    } else {
      throw std::runtime_error("unknown generator type: " + type);
    }

    sat::Formula formula;
    formula.nvars = generated.nvars;
    formula.clauses = std::move(generated.clauses);

    std::string error;
    if (!sat::writeDimacs(out_path, formula, generated.comments, error)) {
      throw std::runtime_error(error);
    }
    std::cerr << "wrote " << out_path << " (" << formula.nvars << " variables, "
              << formula.clauses.size() << " clauses)\n";
    return 0;
  } catch (const std::exception& ex) {
    std::cerr << "error: " << ex.what() << '\n';
    return 1;
  }
}
