// Extract the ELF from the verified local EBOOT with the pinned pspdecrypt library.
#include <fstream>
#include <iostream>
#include <iterator>
#include <vector>

#include "PrxDecrypter.h"

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "Usage: decrypt-prx original-eboot.bin output.elf\n";
        return 1;
    }
    std::ifstream input(argv[1], std::ios::binary);
    std::vector<u8> encrypted((std::istreambuf_iterator<char>(input)), {});
    if (encrypted.size() != 2285536) {
        std::cerr << "Unexpected encrypted EBOOT length\n";
        return 1;
    }
    std::vector<u8> elf(encrypted.size() + 4096);
    int length = pspDecryptPRX(encrypted.data(), elf.data(), encrypted.size());
    if (length != 2285185) {
        std::cerr << "Unexpected decrypted ELF length\n";
        return 1;
    }
    std::ofstream output(argv[2], std::ios::binary);
    output.write(reinterpret_cast<const char*>(elf.data()), length);
    output.close();
    return output ? 0 : 1;
}
