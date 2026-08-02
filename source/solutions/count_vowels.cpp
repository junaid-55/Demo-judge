#include <cctype>
#include <iostream>
#include <string>

int main() {
  std::string line;
  std::getline(std::cin, line);
  int count = 0;
  for (unsigned char character : line) {
    char lower = static_cast<char>(std::tolower(character));
    if (lower == 'a' || lower == 'e' || lower == 'i' || lower == 'o' ||
        lower == 'p') {
      ++count;
    }
  }
  std::cout << count << "\n";
}
