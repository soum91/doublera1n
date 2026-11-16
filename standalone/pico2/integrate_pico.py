#!/usr/bin/env python3
"""Wire the NAND transport into a user's local standalone-usbliter8 source.

Requires the exact MIT autoboot add-on already applied to upstream usbliter8.
Does not fetch/vendor the exploit, build a UF2, connect a phone or flash a board.
The device header stays outside Git in DBNAND_PRIVATE_EXPORT.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zlib

HERE = Path(__file__).resolve().parent
AUTOBOOT_SHA256 = '45d332b333d4604e8af38736b551856c8585ff04601dc8a9240029f385786d3f'
MARKER = '# doublera1n NAND transport integration'

class IntegrationError(ValueError): pass


def integrate(source: Path, private: Path):
    source, private = source.resolve(), private.resolve()
    if private == source or private.is_relative_to(source):
        raise IntegrationError('private export must remain outside the firmware source tree')
    source_file, cmake_file = source / 'autoboot.c', source / 'CMakeLists.txt'
    main_file = source / 'main.c'
    main_text = main_file.read_text()
    old_handoff = '    led_set_state(LED_STATE_SUCCESS);\n\n    printf("\\nsuccess, spinning forever\\n");\n    spin_forever();'
    if main_text.count(old_handoff) != 1 or 'if (autoboot_boot() != 0)' not in main_text:
        raise IntegrationError('unexpected standalone main handoff; refusing an unreviewed success indicator')
    main_text = main_text.replace(old_handoff, '    led_set_state(LED_STATE_IDLE);\n\n    printf("\\nNAND handoff sent; jailbreak startup remains unverified\\n");\n    spin_forever();', 1)
    original = source_file.read_bytes()
    if hashlib.sha256(original).hexdigest() != AUTOBOOT_SHA256:
        raise IntegrationError('unsupported or already-modified autoboot.c; use the exact standalone add-on source')
    cmake = cmake_file.read_text()
    if MARKER in cmake or len(re.findall(r'\bautoboot\.c\b', cmake)) != 1 or not re.search(r'add_executable\s*\(\s*usbliter8\b', cmake):
        raise IntegrationError('CMake must already include the standalone autoboot add-on exactly once')
    report = json.loads((private / 'stage-map.json').read_text())
    image = (private / 'nand-first-stage.raw').read_bytes()
    if report.get('board') != 'd431ap' or report.get('build') != '24A446' or \
            report.get('candidate_sha256') != hashlib.sha256(image).hexdigest() or \
            report.get('candidate_crc32') != zlib.crc32(image) or len(image) != 2842448:
        raise IntegrationError('private candidate metadata or digest mismatch')
    ecid = report.get('ticket_ecid_hex', '')
    if not re.fullmatch(r'[0-9a-f]{16}', ecid) or int(ecid, 16) == 0:
        raise IntegrationError('private candidate lacks its installed-ticket ECID')
    expected = '#pragma once\n#include <stdint.h>\n#define DBNAND_EXPECTED_ECID UINT64_C(0x' + ecid + ')\n'
    if (private / 'nand_device_config.h').read_text() != expected:
        raise IntegrationError('private device header mismatch')
    text = original.decode()
    signature = 'int autoboot_boot(void) {'
    if text.count(signature) != 1:
        raise IntegrationError('unexpected autoboot entry point')
    # Keep the add-on's original code in a separately named, uncalled function.
    # This preserves its own helper references and avoids unused-static build
    # warnings. The existing main calls the new autoboot_boot below.
    text = text.replace(signature, 'int dbnand_legacy_single_image_boot(void) {', 1)
    text = '#include "nand_transport.h"\n#include "nand_usbliter8_adapter.h"\n#include "nand_device_config.h"\n' + text
    text += '''\nint autoboot_boot(void) {
    int result = dbnand_pico_boot(IMAGE, HEADER->size, HEADER->crc32, DBNAND_EXPECTED_ECID);
    INFO("NAND transport result %d (handoff is not proof of jailbreak boot)", result);
    return result == DBNAND_HANDED_OFF ? 0 : -1;
}
'''
    cmake += '''\n''' + MARKER + '''
target_sources(usbliter8 PRIVATE nand_transport.c nand_usbliter8_adapter.c)
if(NOT DEFINED ENV{DBNAND_PRIVATE_EXPORT})
    message(FATAL_ERROR "Set DBNAND_PRIVATE_EXPORT to the private NAND export directory")
endif()
target_include_directories(usbliter8 PRIVATE "$ENV{DBNAND_PRIVATE_EXPORT}")
'''
    # Complete all validation before local source writes. No private header or
    # image is copied into a Git source tree; existing add-on attribution stays.
    for name in ('nand_transport.c', 'nand_transport.h', 'nand_usbliter8_adapter.c', 'nand_usbliter8_adapter.h', 'NAND_TRANSPORT_NOTICE.md'):
        if (source / name).exists(): raise IntegrationError('refusing to overwrite ' + name)
    for name in ('nand_transport.c', 'nand_transport.h', 'nand_usbliter8_adapter.c', 'nand_usbliter8_adapter.h', 'NAND_TRANSPORT_NOTICE.md'):
        (source / name).write_bytes((HERE / name).read_bytes())
    source_file.write_text(text); cmake_file.write_text(cmake); main_file.write_text(main_text)
    return {'integrated': True, 'source': str(source), 'private_material_copied_into_source': False,
            'firmware_built': False, 'device_tested': False, 'uf2_generated': False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root', type=Path, required=True)
    p.add_argument('--private-export', type=Path, required=True)
    a = p.parse_args(argv)
    try:
        print(json.dumps(integrate(a.source_root, a.private_export), indent=2))
    except (IntegrationError, OSError, ValueError, KeyError) as e:
        print('Pico source integration: ' + str(e), file=sys.stderr); return 1
    return 0

if __name__ == '__main__': sys.exit(main())
