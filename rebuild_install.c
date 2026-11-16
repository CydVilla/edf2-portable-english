/* Rebuild the same-size Data Install container for the verified ULJS00374 ISO.
 * Build against the pinned public libkirk source listed in V0.3.md.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "kirk_engine.h"
#include "amctrl.h"

enum { HEADER_SIZE = 0x90, BLOCK_SIZE = 1024, TAG_SIZE = 16 };
static const size_t archive_size = 35885056;
static const size_t container_size = 36445904;

static void fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    exit(1);
}

static u8 *read_exact(const char *path, size_t len) {
    FILE *in = fopen(path, "rb");
    if (!in) fail("Could not open an input file");
    u8 *data = malloc(len);
    if (!data) fail("Could not allocate input buffer");
    if (fread(data, 1, len, in) != len || fgetc(in) != EOF || ferror(in))
        fail("Unexpected input file size");
    fclose(in);
    return data;
}

static void start_mac(MAC_KEY *mac, u8 *data, int size) {
    if (sceDrmBBMacInit(mac, 1) || sceDrmBBMacUpdate(mac, data, size))
        fail("Could not compute PGD MAC");
}

static void check_mac(u8 *data, int size, u8 *tag, u8 *key) {
    MAC_KEY mac;
    start_mac(&mac, data, size);
    if (sceDrmBBMacFinal2(&mac, tag, key))
        fail("PGD authentication failed");
}

static void write_mac(u8 *data, int size, u8 *tag, u8 *key) {
    MAC_KEY mac;
    start_mac(&mac, data, size);
    if (sceDrmBBMacFinal(&mac, tag, key))
        fail("Could not write PGD MAC");
}

int main(int argc, char **argv) {
    if (argc != 5)
        fail("Usage: rebuild_install original.pgd original.vfs translated.vfs output.pgd");
    u8 *container = read_exact(argv[1], container_size);
    u8 *original = read_exact(argv[2], archive_size);
    u8 *translated = read_exact(argv[3], archive_size);
    if (memcmp(container, "\0PGD", 4) || memcmp(original, "VFS\0", 4) ||
        memcmp(translated, "VFS\0", 4))
        fail("Unexpected PGD or VFS signature");
    if (kirk_init()) fail("Could not initialize libkirk");
    u8 header[HEADER_SIZE];
    memcpy(header, container, HEADER_SIZE);
    PGD_DESC *desc = pgd_open(header, 2, NULL);
    if (!desc || desc->mac_type != 1 || desc->cipher_type != 1 ||
        desc->data_offset != HEADER_SIZE || desc->block_size != BLOCK_SIZE ||
        desc->data_size != archive_size || desc->align_size != archive_size ||
        desc->table_offset != HEADER_SIZE + archive_size ||
        desc->block_nr != archive_size / BLOCK_SIZE)
        fail("Unexpected ULJS00374 PGD layout");
    const int tag_bytes = desc->block_nr * TAG_SIZE;
    u8 *table = container + desc->table_offset;
    if (desc->table_offset + tag_bytes != container_size)
        fail("Unexpected PGD tag table size");
    check_mac(table, tag_bytes, container + 0x60, desc->vkey);

    /* pgd_open has already authenticated this fixed-key header. Recover its
       MAC key from that tag so the public libkirk constants stay upstream. */
    MAC_KEY mac;
    u8 header_key[TAG_SIZE];
    start_mac(&mac, container, 0x80);
    if (bbmac_getkey(&mac, container + 0x80, header_key))
        fail("Could not verify PGD header key");

    unsigned changed = 0;
    for (unsigned b = 0; b < desc->block_nr; b++) {
        size_t pos = (size_t)b * BLOCK_SIZE;
        u8 *ciphertext = container + HEADER_SIZE + pos;
        u8 *tag = table + TAG_SIZE * b;
        check_mac(ciphertext, BLOCK_SIZE, tag, desc->vkey);
        memcpy(desc->block_buf, ciphertext, BLOCK_SIZE);
        pgd_decrypt_block(desc, b);
        if (memcmp(desc->block_buf, original + pos, BLOCK_SIZE))
            fail("The original disc and installed VFS disagree");
        if (!memcmp(original + pos, translated + pos, BLOCK_SIZE))
            continue;

        /* The PGD block cipher transforms bytes by XORing a seeded stream.
           Applying it in either direction keeps the original key and offset. */
        memcpy(desc->block_buf, translated + pos, BLOCK_SIZE);
        pgd_decrypt_block(desc, b);
        memcpy(ciphertext, desc->block_buf, BLOCK_SIZE);
        write_mac(ciphertext, BLOCK_SIZE, tag, desc->vkey);
        pgd_decrypt_block(desc, b);
        if (memcmp(desc->block_buf, translated + pos, BLOCK_SIZE))
            fail("New PGD block failed its round trip");
        changed++;
    }
    write_mac(table, tag_bytes, container + 0x60, desc->vkey);
    write_mac(container, 0x70, container + 0x70, desc->vkey);
    write_mac(container, 0x80, container + 0x80, header_key);
    memcpy(header, container, HEADER_SIZE);
    PGD_DESC *verified = pgd_open(header, 2, desc->vkey);
    if (!verified) fail("Rebuilt PGD header failed verification");
    check_mac(table, tag_bytes, container + 0x60, verified->vkey);
    pgd_close(verified);
    pgd_close(desc);

    FILE *out = fopen(argv[4], "wbx");
    if (!out) fail("Could not create a new PGD output file");
    if (fwrite(container, 1, container_size, out) != container_size || fclose(out))
        fail("Could not write the rebuilt PGD");
    printf("Validated %zu PGD blocks and rebuilt %u.\n", archive_size / BLOCK_SIZE, changed);
    free(container);
    free(original);
    free(translated);
    return 0;
}
