#include <iostream>
#include <string>
using namespace std;
bool is_pallindrome(string &str) {
  if (sizeof(str) == 0 || sizeof(str) == 1)
    return true;
  for (int i = 0; i < sizeof(str); i++) {
    if (str[i] != str[sizeof(str) - 1 - i])
      return false;
  }
  return true;
}

int main() {
  string line;
  getline(cin, line);
  if (is_pallindrome(line))
    cout << "YES" << endl;
  else
    cout << "NO" << endl;
}
