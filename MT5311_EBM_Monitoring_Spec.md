# Metanoia MT5311 EBM Monitoring Protocol – Read-Only Profile

```
Document:   MT5311-EBM-SPEC-RO
Version:    1.6
Date:       2026-10-14
Category:   Informational (unofficial)
```

## Abstract

This document specifies the read-only subset of the layer-2 management protocol ("EBM")
used to monitor a Metanoia MT5311 VDSL2 modem (SFP form factor) from a host computer
over Ethernet: session setup and read access to the modem's DSP memory. Requests that
modify the device are out of scope. All status, performance and configuration data is exposed as
variables at fixed DSP memory addresses. This document also lists those addresses for
the known firmware layouts and specifies how the most important variables are
interpreted.

## Status of This Document

This is an independent, unofficial description, written to enable interoperable
monitoring software. It is not an official vendor document and is not affiliated with
or endorsed by any vendor. Product and company names are used only to identify the
hardware they refer to and may be trademarks of their respective owners.

Verification status:

- **Verified on a device** (firmware `750202`, 2018-09-07, RT, VDSL2 profile 17a, in and
  out of showtime): frame format, CONNECT, READ including several commands per request
  (5.5), sequence handling, the identification words, the memory layout of firmware
  branch 1.60 (8.2), and the registers and encodings that the sections below state as
  observed.
- **Not verified**: DISCONNECT and all registers not stated as observed.

Encodings, scalings and value lists that are not stated as observed are taken from the
firmware and from RFC 5650. Implementations SHOULD keep register addresses, scalings
and value lists in data tables so that they can be corrected without code changes.

Statements marked **[UNVERIFIED]** are consistent with all available information but
have not been observed on a live device. Appendix C lists them all.

## Table of Contents

1. Introduction
2. Conventions and Terminology
3. Protocol Overview
4. Frame Format
5. Messages
6. Transaction Rules
7. Memory Model
8. Address Layouts
9. Register Semantics
10. Device Modification (Out of Scope)
11. Monitoring Procedure
12. Security Considerations
- Appendix A. Register Reference
- Appendix B. Example Exchanges
- Appendix C. Unverified Items and Open Issues

---

## 1. Introduction

The MT5311 is a VDSL2 modem built around a 24-bit DSP. Its firmware keeps the
state of the line in global variables in DSP data memory, largely following the
structure of the VDSL2 line MIB (RFC 5650 / ITU-T G.997.1). A management host reads
these variables directly over Ethernet.

The protocol has no notion of objects, OIDs or tables. The host addresses raw memory
words. The meaning of an address depends on the firmware build (Section 8).

## 2. Conventions and Terminology

The key words "MUST", "MUST NOT", "REQUIRED", "SHOULD", "SHOULD NOT", "RECOMMENDED",
"MAY" and "OPTIONAL" are to be interpreted as described in BCP 14 (RFC 2119, RFC 8174).

- **Host**: the management computer.
- **Device**: the MT5311 modem.
- **Word**: one 24-bit DSP memory word, transferred as 3 bytes.
- **Space**: one of the DSP memory spaces X, Y or P.
- **OT / RT**: Office Terminal (xTU-C, network side) / Remote Terminal (xTU-R, customer side).
  A device runs as either OT or RT.
- **US / DS**: upstream (RT → OT) / downstream (OT → RT).
- **Showtime**: the line is synchronised and carries data.

Notation:

- `0x` prefixes and backticked hex strings such as `00001D` denote hexadecimal values.
- `X:006C35` denotes word address `0x006C35` in space X.
- All multi-byte protocol fields are big-endian (network byte order).
- Byte offsets in Sections 4 and 5 are relative to the first byte after the Ethernet
  header unless stated otherwise.

## 3. Protocol Overview

- Transport: raw Ethernet II frames, EtherType `0x6120`. No IP is involved.
- Pattern: strict request/response. The host sends one request and waits for the
  matching response before it sends the next request.
- Operations: CONNECT (session setup), READ (one or more words), DISCONNECT.
- Addressing: the host addresses the device by its MAC address. The device answers to
  the host's MAC address. The host needs to know the device MAC address (6.1).

```
Host                                    Device
 |-- CONNECT stage 1 (0x31) ----------->|
 |<------------------- 0xB1, status E0 -|
 |-- CONNECT stage 2 (0x31, "noia") --->|
 |<------------------- 0xB1, status E1 -|
 |-- READ  (0x01, addr) --------------->|
 |<------------------ 0x81, data word --|
 |              ...                     |
```

## 4. Frame Format

### 4.1. Ethernet Encapsulation

| Offset (frame) | Size | Field |
|---:|---:|---|
| 0 | 6 | Destination MAC address |
| 6 | 6 | Source MAC address |
| 12 | 2 | EtherType = `0x6120` |
| 14 | n | EBM message (Section 4.2) |

- Requests MUST be padded with zero bytes to a total frame length of 64 bytes
  (excluding FCS).
- Responses are 60 bytes long (Ethernet minimum, excluding FCS). Bytes beyond the
  message are padding and MUST be ignored.
- A receiver SHOULD discard frames with another EtherType and frames whose source MAC
  address is its own.

### 4.2. Message Header

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|            Length             |     Type      |   Sequence    :
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
:            Sequence (cont.)                   |    Status     |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Payload ...
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-
```

| Offset | Size | Field | Description |
|---:|---:|---|---|
| 0 | 2 | Length | See 4.3 |
| 2 | 1 | Type | Message type (Section 5) |
| 3 | 4 | Sequence | Transaction sequence number (Section 6) |
| 7 | 1 | Status | Requests: `0xFF`. Responses: see 4.4 |
| 8 | var | Payload | Type-specific |

### 4.3. Length Field

- In a **request**, Length is the payload length in bytes, counted from offset 8.
- In a **response**, Length is 6 plus the payload length. It covers the Type,
  Sequence and Status fields plus the payload.
- A host MUST set Length as specified for each request type. A host MAY ignore
  Length in responses.

### 4.4. Type and Status

The response Type is the request Type with the most significant bit set
(`Type | 0x80`).

| Status | Meaning |
|---|---|
| `0xFF` | Request (always) |
| `0x00` | Response: success (READ) |
| `0xE0` | Response to CONNECT stage 1 |
| `0xE1` | Response to CONNECT stage 2 |
| other | Response: error |

## 5. Messages

| Request Type | Response Type | Name |
|---|---|---|
| `0x31` | `0xB1` | CONNECT |
| `0x01` | `0x81` | READ |
| `0x50` | none | DISCONNECT |

### 5.1. CONNECT

CONNECT sets up a session in two stages. Stage 2 MUST only be sent after a valid
stage 1 response.

**Stage 1 request** (Length = 8):

| Offset | Size | Value |
|---:|---:|---|
| 8 | 4 | `0xFFFFFFFF` |
| 12 | 4 | Parameter of unknown meaning (possibly a session timeout). A host SHOULD send `0x00000000`. |

**Stage 1 response** (Type `0xB1`, Status `0xE0`, Length = 14):

| Offset | Size | Value |
|---:|---:|---|
| 8 | 4 | `0x00000002` (meaning unknown) |
| 12 | 4 | Magic `0x95743926` |

A host MUST accept a stage 1 response only if all of the following hold: Type is
`0xB1`, the source MAC equals the device MAC, Status is `0xE0` and the magic matches.

**Stage 2 request** (Length = 4):

| Offset | Size | Value |
|---:|---:|---|
| 8 | 4 | `0x6E6F6961` (ASCII `"noia"`) |

The following bytes are padding (4.1) and SHOULD be zero.

**Stage 2 response** (Type `0xB1`, Status `0xE1`, Length = 12): 6 payload bytes
(offsets 8–13), all zero. A host MUST accept it only if Type, source MAC and Status match.

### 5.2. READ

Reads one word.

**Request** (Length = 6):

| Offset | Size | Field | Description |
|---:|---:|---|---|
| 8 | 1 | Space | `1` = X, `2` = Y, `3` = P (Section 7.1) |
| 9 | 3 | Address | Word address |
| 12 | 2 | Count | MUST be `0x0003` (bytes; one word). See below. |

**Response** (Type `0x81`, Length = 9):

| Offset | Size | Field |
|---:|---:|---|
| 7 | 1 | Status (`0x00` = success) |
| 8 | 3 | Data word, most significant byte first |

### 5.3. Other Request Types

Request types other than those in this section are out of scope (Section 10). A
monitoring host MUST NOT send them.

### 5.4. DISCONNECT

Presumably ends the session. Type `0x50`, Length `0`, Status `0xFF`, no payload. The
Sequence field carries the current counter value; the host increments the counter
afterwards. The device sends no response, and the host MUST NOT wait for one.
[UNVERIFIED]

DISCONNECT has not been observed on the wire, and its effect on the device is unknown.
A host MAY send it when it ends a session; a host that omits it interoperates, since a
session needs no teardown (6.4).

### 5.5. Several Commands per Request

A READ request MAY carry several read commands. The payload is then a sequence of n
6-byte commands, each with the layout of 5.2 (Space, Address, Count = `0x0003`), and
Length is `6 · n`. The response carries the n data words in the order of the commands:
Type `0x81`, Status `0x00`, Length `6 + 3 · n`.

```
H→D  003c 01 00000005 ff  01 006fd7 0003  01 006fdb 0003  …  (10 commands)
D→H  0024 81 00000005 00  000003 000005 …                   (10 words)
```

- Requests of up to 64 commands (406-byte frames) and the matching responses (214-byte
  frames) have been observed. A request frame longer than 64 bytes is not padded.
- The commands of one request MAY address unrelated registers.
- A host SHOULD keep n ≤ 64. Error handling for multi-command requests (no response,
  error response) is defined in 6.4.
- Whether the device reads the words of one request atomically (from the same
  instant) is not known. [UNVERIFIED]
- A single command with Count > 3 has not been observed; a host MUST NOT use it.

A host that polls many registers SHOULD use multi-command requests; one request per poll
cycle is typically sufficient.

### 5.6. Legacy Short Format

A second, older request format exists on the same EtherType. It is mentioned here only
so that a receiver can recognise it; a host MUST NOT use it.

| Offset | Size | Field |
|---:|---:|---|
| 0 | 2 | Length = `0x0007` |
| 2 | 1 | Control: bits 7–6 port, bit 5 operation, bit 4 space P, bit 3 space Y (neither: X), bits 2–0 sequence (mod 8) |
| 3 | 2 | Word address (16 bits) |
| 5 | 3 | Data word (zero for a read) |
| 8 | 2 | CRC |

The Length value `0x0007` does not equal the number of bytes that follow it (8); its
exact definition is not known. The device answers a read in this format with Length
`0x0006`, the echoed control byte
and address, and three data bytes (see Appendix C). In such a response the byte at
offset 2 has bit 7 clear, so it never matches a request under 6.2 and is discarded.

## 6. Transaction Rules

### 6.1. Addressing

The host sends every request to the device MAC address. The device answers to the
source MAC address of the request.

A host MUST be configured with the device MAC address. No discovery mechanism is known.
Whether the device answers a CONNECT sent to the broadcast address is not known
[UNVERIFIED]. A host that tries this MUST take the device MAC address from the source
address of the stage 1 response and use it for all further requests.

### 6.2. Sequence Numbers and Response Matching

1. The host keeps one 32-bit sequence counter per session. Its initial value is
   arbitrary; `0x00000001` is customary.
2. Every request carries the current counter value. The device copies it into the
   response unchanged.
3. CONNECT (both stages, including retransmissions) uses the current counter value and
   does not advance it. The first READ after CONNECT therefore carries the
   same Sequence as the CONNECT requests.
4. After a READ, the host increments the counter by one: after a matching
   response, and also after it abandons the request.
5. A host MUST NOT have more than one request outstanding.

A response matches the outstanding request only if all of the following hold:

- the source MAC address is the device MAC address,
- Type equals the request Type with bit 7 set (`Type | 0x80`),
- Sequence equals the request's Sequence,
- for CONNECT: Status is the value expected for the stage (`0xE0` or `0xE1`).

A host MUST silently discard every other frame. Checking Type is required: CONNECT and
the first READ share a Sequence value, so a late CONNECT response would otherwise be taken
as a READ response.

A READ response with matching Type and Sequence but a Status other than `0x00`
is an error response. The request MUST NOT be retransmitted in that case; its handling
is defined in 6.4.

The device does not require consecutive Sequence values; it echoes whatever value it
receives. A host that also increments the counter after each CONNECT stage
interoperates as well.

### 6.3. Timing

- If no matching response arrives within the timeout, the host retransmits the identical
  request (same Sequence). It SHOULD make at most 3 attempts in total.
- Recommended timeout: 200 ms per attempt. Typical device response time is below 1 ms;
  the maximum observed is 15 ms.
- No minimum interval between requests is known to be required. Intervals down to 7 ms
  between a response and the next request have been used without problems; faster
  operation is untested. A host that polls many registers SHOULD keep at least 5 ms
  between requests until faster operation has been tested. [UNVERIFIED]
- A host MAY send each CONNECT stage up to 3 times; repeated valid responses are
  harmless.

### 6.4. Session Lifetime and Recovery

No session timeout is known, and a session needs no teardown; the effect of DISCONNECT
(5.4) is unknown. It is not known how the device answers a READ that is not preceded by
CONNECT, e.g. after a device reset [UNVERIFIED].

**Session errors.** A host SHOULD treat each of the following as a session error and
SHOULD then perform CONNECT again before it continues:

- a single-command READ of the identification block (8.2) that remains unanswered after
  all attempts (6.3) or receives an error response,
- an implausible identification block, i.e. `xdslMetanoiaSignature` ≠ `474154` or a
  change of `xdslFirmwareVer`, `xdslFirmwareDate` or `xdslFirmwareTime`. A changed
  firmware MUST lead to a new layout selection (8.2).

**Failed status requests.** If any other READ remains unanswered after all attempts or
receives an error response, the host SHOULD proceed in this order:

1. Read the identification block with single-command requests. If this fails, the
   session error rules above apply; the failed request is repeated in the new session.
2. If the failed request carried one command, mark that register as described below
   and continue without it.
3. If the failed request carried several commands, read each of its registers with a
   single-command request and mark every register whose read fails. The remaining
   registers MAY be combined into multi-command requests again.

An error response to a multi-command request does not identify the failing command;
step 3 finds it. A register is marked according to how its single-command read failed:

- **Error response** (Status ≠ `0x00`): the register is **unreadable**. It SHOULD NOT
  be requested again until the next layout selection.
- **No response** after all attempts: the register is **suspended**. It SHOULD be
  requested again after a hold-off time, e.g. 5 minutes, and is then treated like any
  other register. A host MAY double the hold-off time after each further failure of the
  same register, up to a limit, e.g. 1 hour.

A host that follows these rules never reconnects because of a single failing register,
and lost frames never exclude a register permanently.

Repeated CONNECT is harmless. A host SHOULD wait at least 1 s between reconnection
attempts.

## 7. Memory Model

### 7.1. Spaces and Words

| Space | Wire value | Content |
|---|---|---|
| X | `1` | Data memory: all status, statistics and configuration variables |
| Y | `2` | Data memory: internal tables [UNVERIFIED] |
| P | `3` | Program memory [UNVERIFIED] |

All variables in this document are in space X. Each variable occupies one or more
consecutive words. A multi-word variable at address A occupies A, A+1, …, A+n-1 and
is read word by word.

Addresses at and above `X:FFF000` are DSP peripheral registers, not firmware variables.

### 7.2. Number Formats

- Unsigned values (`Unsigned32`, `Counter32`, `Gauge32`): the word is an unsigned
  integer 0 … 16 777 215.
- Signed values (`Integer32`): the word is a 24-bit two's complement integer. Bit 23
  is the sign.
- Text (`OCTET STRING`): 3 bytes per word, most significant byte first.
- Scale and unit are given per register in Appendix A (e.g. `0.1dB`: value / 10 = dB).
- Counters (`Counter32` and all event counters) are only 24 bits wide. They wrap from
  `FFFFFF` to `000000`. A host that computes differences MUST do so modulo 2^24 and
  SHOULD poll often enough that a counter cannot advance by 2^24 between two polls.
- Interval counters are reset at the end of their interval. Each interval table has its
  own elapsed-time word with the same index:

  | Counters | Elapsed time |
  |---|---|
  | `xdsl2PMLCurr{15M,1Day}*<i>` | `xdsl2PMLCurr{15M,1Day}TimeElapsed<i>` |
  | `xdsl2PMChCurr{15M,1Day}*<i>` | `xdsl2PMChCurr{15M,1Day}TimeElapsed<i>` |
  | `xdsl2PMLInitCurr{15M,1Day}*<i>` | `xdsl2PMLInitCurr{15M,1Day}TimeElapsed<i>` |

  A decrease of a counter together with a decrease of its elapsed-time word is a reset,
  not a wrap.
- Showtime counters (the `Curr` instances of the vendor counter tables, 9.1, and
  `xdslMetanoiaShowtimeSeconds`, 9.3.6) are reset when a new showtime starts. A
  decrease of such a counter after the line has left showtime since the previous poll
  is a reset, not a wrap. A host that cannot tell (e.g. because a whole retrain fell
  between two polls) SHOULD treat a decrease as a reset if
  `xdslMetanoiaShowtimeSeconds` has also decreased.
- Snapshot values (class `S`, 7.3, e.g. `…LastSec…`) hold the count of the last
  completed interval. They are not cumulative; a host MUST NOT compute differences of
  them.
- Some 48-bit counters are split into two words named `…Hi` and `…Lo`. The value is
  presumably `Hi · 2^24 + Lo` [UNVERIFIED]. The two words MAY be read in one
  multi-command request (5.5), but it is not known whether such a request is read
  atomically. A host SHOULD therefore read `Hi`, `Lo`, `Hi` (in one request or in
  separate requests) and repeat if the two `Hi` values differ.

### 7.3. Special Values

| Raw word | Meaning |
|---|---|
| `7FFFFF` | Not available (G.997.1 special value) |
| `7FFFFE` | Not available / not applicable (G.997.1 special value) |
| `C69A53` | Invalid / not initialised |
| `FFFFCC` | Invalid |
| `19979F` | Out of range |

Appendix A assigns each register a value class (column "Class"). The class, not the
MIB type, decides how a host interprets the raw word:

| Class | Meaning | Special values |
|---|---|---|
| `M` | Measurement value with a known unit: rates, margins, attenuation, transmit power, delay, INP, framing parameters | Apply. A host SHOULD map them to "no value" before scaling. |
| `C` | Counter or elapsed time (7.2). Every 24-bit pattern is a valid count. | MUST NOT be applied. |
| `S` | Snapshot count of the last completed interval (7.2) | MUST NOT be applied. |
| `E` | Enumeration, bit mask, flag or state word | MUST NOT be applied; unknown values are reported as numbers. |
| `I` | Identification word or text | MUST NOT be applied. |
| `K` | Configuration value | Not defined; a host SHOULD report the raw value. |
| `–` | Other; no type, unit or interpretation defined (e.g. the G.INP status values in A.6) | Not defined; a host SHOULD report the raw value. |

`FFFFCC` is ambiguous: as `Integer32` it is the valid value −52 (e.g. an SNR margin of
−5.2 dB). A host SHOULD treat `FFFFCC` as "no value" only for class `M` registers of an
unsigned type. [UNVERIFIED]

Status values (rates, margins, attenuation, delay, INP) are only meaningful while the
line is in showtime (Section 9.2.1).

## 8. Address Layouts

### 8.1. Layouts and Firmware Builds

Variable addresses differ between firmware builds. Builds of the same firmware branch
share an address layout. This document describes two layouts:

| Layout | Known builds (`xdslFirmwareDate`_`xdslFirmwareTime`) |
|---|---|
| Branch 1.60 | `020818_163044`, `052918_102728`, and firmware `750202` / `090718_173044` |
| Branch 1.61 | `080217_190152` |

Between the branches, the identification and configuration block from `X:006C31` is
unchanged; in branch 1.60 the registers from 1.61 address `X:006DF2` to `X:006F20` lie
24 words lower and those from `X:006F22` 21 words lower. Other areas are shifted by
other amounts (e.g. +3 words for `nO_*`). Appendix A lists the address in both layouts;
a host MUST NOT compute one from the other by a fixed offset.

### 8.2. Firmware Identification and Layout Selection

The following words have the same addresses in all known builds. A host SHOULD read
them right after CONNECT.

| Address | Symbol | Format |
|---|---|---|
| `X:006C31` | `xdslFirmwareVer` | See 9.2.3 |
| `X:006C32` | `xdslFirmwareDate` | `MMDDYY` |
| `X:006C33` | `xdslFirmwareTime` | `hhmmss` |
| `X:006C34` | `xdslBoardType` | Bits 7–0: board type (`0x68` = 104 = MT5311 SFP) |
| `X:006C35` | `xdslTerminal` | See 9.2.1 |
| `X:006C36` | `xdslMetanoiaSignature` | ASCII `"GAT"` (`474154`) |

**Selection.** Firmware `750202`, date `090718`, time `173044` (2018-09-07 17:30:44) uses
the **branch 1.60** layout; this has been verified on a device. A host MUST use the 1.60
addresses (Appendix A, column "Addr 1.60") for this build. The version number
`xdslFirmwareVer` does not identify the layout.

For every other build, including the other builds listed in 8.1, a host MUST select the
layout with the layout check below; the table in 8.1 is informational only. A host
SHOULD also run the check for `750202`; it costs one request.

**Layout check.** A host determines the layout by checking constants that the firmware
never changes. A layout is accepted only if all of the following words read as expected
at its addresses:

| Register | Expected | Addr 1.60 | Addr 1.61 |
|---|---|---|---|
| `xdsl2LineBand6` | `000006` (ds2) | `X:006FEF` | `X:007004` |
| `xdsl2LineBand7` | `000008` (ds3) | `X:006FF3` | `X:007008` |
| `xdsl2LineBand8` | `00000A` (ds4) | `X:006FF7` | `X:00700C` |
| `xdsl2LineBand9` | `000001` (upstream) | `X:006FFB` | `X:007010` |
| `xdsl2LineBand10` | `000002` (downstream) | `X:006FFF` | `X:007014` |
| `xdsl2ChStatusUnit0` | `000001` (xtuc) | `X:007003` | `X:007018` |
| `xdsl2ChStatusUnit1` | `000001` (xtuc) | `X:007011` | `X:007026` |

The values are the `Xdsl2Band` and `Xdsl2Unit` codes of RFC 5650. The check works in
any line state; all 14 words fit into one multi-command request (5.5). On a branch 1.60
device the expected values have been observed at the 1.60 addresses; the 1.61
addresses are taken from the address layout and have not been checked on a branch 1.61
device [UNVERIFIED]. Exactly one layout SHOULD pass; if none or several pass, the host
MUST NOT interpret status registers and SHOULD report the firmware as unsupported.

The remaining constants of the same tables follow the same scheme and MAY be added to
the check: `xdsl2LineBand0`–`5` = `3, 5, 7, 9, 11, 4` (us0–us4, ds1);
`xdsl2ChStatusUnit2`, `…3` = `2` (xtur).

**Showtime plausibility.** In showtime a host MAY additionally check, at the addresses
of the selected layout:

1. `xdsl2LineStatusXtuTransSys` is one of the values in 9.3.2.
2. If that value indicates VDSL2: `xdsl2LineStatusActProfile` has exactly one of bits
   0–7 set (9.3.3).
3. `xdsl2LineStatusAttainableRateDs` is not a special value (7.3), not `0`, and not
   above 300000 kbit/s.

## 9. Register Semantics

Addresses in Section 9 refer to firmware branch 1.60 (Section 8.2). Appendix A lists all registers.

### 9.1. Direction and Band Indices

Many variables exist in several instances that differ in a trailing index. Most tables
contain a `…Unit<i>` word that names the transceiver unit an instance belongs to
(`Xdsl2Unit`: `1` = xtuc, `2` = xtur). Values of the xTU-C unit describe the upstream
direction (received by the xTU-C), values of the xTU-R unit the downstream direction.

| Register family | Upstream (xtuc) | Downstream (xtur) | Unit |
|---|---|---|---|
| `xdsl2ChStatus{ActDataRate,PrevDataRate}<i>` | `0` | `2` | kbit/s |
| `xdsl2ChStatusActDelay<i>` | `0` | `2` | ms |
| `xdsl2ChStatusActInp<i>` | `0` | `2` | 0.1 symbols |
| `xdsl2ChStatus{IntlvDepth,IntlvBlock,…}<i>` | `0` | `2` | |
| `xdsl2LineStatusAttainableRate{Us,Ds}` | `Us` | `Ds` | kbit/s |
| `xdsl2LineStatusActAtp{Us,Ds}` | `Us` | `Ds` | 0.1 dBm, signed |
| `xdsl2LineBandStatus{SnrMargin,SigAtten,LnAtten}<i>` | `0`–`4` = US0–US4, `9` = total | `5`–`8` = DS1–DS4, `10` = total | 0.1 dB |
| `xdsl2PMLCurr{15M,1Day}*<i>`, `xdsl2PMLInitCurr*<i>` | `0` | `1` | count, time in s |
| `xdsl2PMChCurr{15M,1Day}*<i>` | `0` | `2` | count |
| `xdsl2LInv*<i>` (inventory) | `0` = xTU-C | `1` = xTU-R | |

Channel indices `1` (xtuc) and `3` (xtur) belong to a second bearer channel and are
normally unused. [UNVERIFIED]

Observed in showtime on an RT device (17a line), consistent with the units above:
`xdsl2LineBandStatusSnrMargin10` = `000021` (3.3 dB), `…SigAtten10` = `0000FB`
(25.1 dB), `…LnAtten10` = `000103` (25.9 dB), `xdsl2LineStatusActAtpDs` = `000080`
(12.8 dBm), `xdsl2LineStatusActAtpUs` = `FFFFE3` (−2.9 dBm, signed). On an RT device the
upstream totals `…SigAtten9` and `…LnAtten9` read `7FFFFE`, while `…SnrMargin9` is
valid (observed `00003C`, 6.0 dB). The per-band upstream values (indices `0`–`4`) are
available for the bands in use; unused bands read `7FFFFE`.

A second observation on the same device and line, about 15.8 h after synchronisation,
gave, decoded with the units above: actual data rate DS 79613 kbit/s, US 33900 kbit/s;
attainable rate DS 107868 kbit/s, US 49011 kbit/s; SNR margin DS 10.7 dB, US 15.9 dB;
DS line/signal attenuation 11.5/12.3 dB; upstream line/signal attenuation per band
US0 2.2/2.2 dB, US1 9.9/10.1 dB, US2 16.4/15.4 dB, with US3 and US4 reading `7FFFFE`;
transmit power DS 11.6 dBm, US −1.6 dBm. All values are plausible for the line; no
reference measurement of another modem is available to confirm the scalings.

`xdsl2ChStatusActDelay0`/`2` and `xdsl2ChStatusActInp0`/`2` read `0` in both
observations. This is consistent with a line without interleaving, but it is not known
whether these registers are maintained when retransmission (G.INP) is in use, which
reports its values in `xdslRtxChStatus*` (A.6) [UNVERIFIED].

**Upstream attenuation on an RT device.** A host on an RT device SHOULD report upstream
signal and line attenuation per band (indices `0`–`4`, skipping special values) and
SHOULD NOT report an upstream total. This document defines no method to compute a total
from the band values; a host that derives one anyway MUST label it as derived. If the
totals `…SigAtten9`/`…LnAtten9` hold a regular value (e.g. on other firmware), the host
SHOULD report it.

**Vendor counter tables.** The variables
`xdslMetanoia{Ot,Rt}[Curr|LastSec]{CorrectedBlocks,CodingViolations,Fecs,Es,Ses,Loss,Uas}<i>`
form two tables: `Ot` for the xTU-C and `Rt` for the xTU-R. Without prefix a counter
counts since start-up, `Curr` counts in the current showtime, `LastSec` holds the value
of the last second.

| Instance | Meaning | Direction for `Ot` | Direction for `Rt` |
|---|---|---|---|
| index `0` | near-end, measured by the unit itself | US | DS |
| index `1` | far-end, as reported by the peer | DS | US |

For index `1` only `CorrectedBlocks` and `CodingViolations` are maintained. The
instances `Fecs1`, `Es1`, `Ses1`, `Loss1` and `Uas1` (with every prefix) are **not
maintained**; a host MUST NOT report them.

An RT device updates the `Rt` table. Observed in showtime:
`xdslMetanoiaRtCurrCorrectedBlocks0` counts downstream FEC corrections; after 56735 s
of showtime it read 14868, while `xdslMetanoiaRtCurrCorrectedBlocks1` (upstream, as
reported by the peer) read 3 and both `…CodingViolations0`/`1` read 0. A host on an RT
device SHOULD therefore take the downstream CRC and FEC counts from
`xdslMetanoiaRt[Curr]{CodingViolations,CorrectedBlocks}0` and the upstream counts from
index `1` of the same table. The `Ot` table of an RT device also holds non-zero values
that differ from the `Rt` table; their meaning is unknown and a host on an RT device
SHOULD NOT report them. The standard counters
`xdsl2PMChCurr{15M,1Day}{CodingViolations,CorrectedBlocks}<i>` (index `0` = US, `2` = DS)
are an alternative for interval-based reporting.

### 9.2. Identification and State

#### 9.2.1. `xdslTerminal` (X:006C35)

| Bits | Meaning |
|---|---|
| 0 | `0` = OT, `1` = RT |
| 3, 6 | Chip family: bit 6 = 0 → bit 3 = 1: AURORA, bit 3 = 0: ARGO; bit 6 = 1 → bit 3 = 1: BARTON, bit 3 = 0: BORA |
| 8–9 | Line state: `0` idle, `1` handshake, `2` training, `3` showtime |
| others | Unknown |

Examples (observed): `000029` = RT, AURORA, idle; `000329` = RT, AURORA, showtime.

Bit 0 tells which unit the device itself is: an OT device is the xTU-C, an RT device
the xTU-R. Its own instance of a unit-indexed variable is the xTU-C instance on OT and
the xTU-R instance on RT (9.1); e.g. the own firmware version is
`xdsl2LInvVersionNumber0` on OT and `xdsl2LInvVersionNumber1` on RT.

#### 9.2.2. `ModemStatus` (X:00001D), `ModemErrOvrflow` (X:006D73), `ModemErrBuf` (X:006D53)

- `ModemStatus = 00000F` means showtime (observed). `000011` has been observed in
  another line state. Other values are undocumented. Use `xdslTerminal` bits 8–9 for
  the line state.
- `ModemErrOvrflow` bit 1 indicates an error condition. Its exact meaning is unknown.
  The value `000001` has been observed in normal showtime.
- `ModemErrBuf` is an error buffer of 32 words. Its format is unknown.

#### 9.2.3. Firmware Identification Words

| Register | Format | Example |
|---|---|---|
| `xdslFirmwareVer` (X:006C31) | Bits 23–16: major; bits 15–0: minor | `750202` |
| `xdslFirmwareDate` (X:006C32) | `MMDDYY`, each hex nibble pair read as a decimal number (BCD) | `090718` = 2018-09-07 |
| `xdslFirmwareTime` (X:006C33) | `hhmmss` (BCD) | `173044` = 17:30:44 |
| `xdslMetanoiaSignature` (X:006C36) | 3 ASCII characters | `474154` = `GAT` |

#### 9.2.4. Inventory Firmware Version

`xdsl2LInvVersionNumber0` (X:0079CE, OT) / `xdsl2LInvVersionNumber1` (X:0079EA, RT),
6 words each.

1. Read the 6 words and concatenate the bytes, most significant first.
2. The format depends on `xdslTwConfig3` (X:006E6F) bit 19:
   - **Bit 19 = 1**: The bytes are ASCII characters. The text ends at the first zero
     byte; a host SHOULD also strip trailing spaces. A text without a zero byte uses
     all 18 bytes.
   - **Bit 19 = 0**: The first 7 bytes are base-62 digits (`a`–`z` = 0–25,
     `A`–`Z` = 26–51, `0`–`9` = 52–61). The version is
     `d0 "_" (d1·62 + d2) "_" (d3·62 + d4) "_" (d5·62 + d6)`, e.g. `1_58_2_30`.
     [UNVERIFIED]

Observed on an RT device in showtime: `xdslTwConfig3` = `1C62C0` (bit 19 set),
`xdsl2LInvVersionNumber0` = `"20.2.2.6 VE_13_1"` (the peer, a Broadcom xTU-C) and
`xdsl2LInvVersionNumber1` = `"1_60_8255 MT5311"` (the device itself).

#### 9.2.5. G.994.1 Vendor ID

`xdsl2LInvG994VendorId0` (X:0079C8, xTU-C) and `xdsl2LInvG994VendorId1` (X:0079E4,
xTU-R), 3 words = 9 bytes each, hold the vendor ID exchanged in G.994.1. On an RT device
the peer's (network side) vendor ID is `xdsl2LInvG994VendorId0` and its own is
`xdsl2LInvG994VendorId1`.

| Bytes | Content |
|---|---|
| 0–1 | ITU-T T.35 country code |
| 2–5 | Provider code, 4 ASCII characters (e.g. `BDCM`) |
| 6–7 | Vendor-specific information |
| 8 | Unused |

The values are valid after the G.994.1 handshake. Observed on an RT device:
`xdsl2LInvG994VendorId0` = `B50042 44434D 1CC000` (country `B500`, provider `BDCM`,
vendor-specific `1CC0`), `xdsl2LInvG994VendorId1` = `B5004D 455441 000000` (`META`).
A later observation of the same line showed the vendor-specific bytes `86D0` from the
same provider (`B500 BDCM 86D0`).

#### 9.2.6. Ethernet Data Path

The host interface mode follows from four registers. In showtime the host reads the
hardware registers; otherwise it reads their configuration copies.

| Role | Hardware register | Configuration copy |
|---|---|---|
| MII control | `Miicr` (X:FFFF94) | `CfgM2MiiCfgReg` (X:006C4F) |
| UTP/PHY | `Utpfr` (X:FFFFA3) | `CfgM2UtpCfgReg` (X:006C50) |
| PLL | `Pll1Ctl` (X:FFF70D) | `CfgPll1Ctl` (X:006D80) |
| HW configuration | `xdslCfgHwConfig` (X:006C3C) | (same) |

| MII | UTP | PLL | HW config | Interface |
|---|---|---|---|---|
| `2FF318` or `2F7318` | `040080` | `015014` | `000002` | RGMII |
| `2FF318` or `2F7318` | `040080` | `011014` | `000000` | RGMII |
| `2F3318` | `440000` | `000204` | `000002` | MII, MAC mode |
| `2F3318` | `400000` or `440000` | `000204` | `000000` | MII, PHY mode |

#### 9.2.7. VCXO

`xdslMetanoiaOtVcxo` (X:007E72) and `xdslMetanoiaRtVcxo` (X:007EAC) hold a snapshot of
the VCXO control value. They are usually displayed in hexadecimal.

### 9.3. Line Status

#### 9.3.1. Validity

Line status variables are valid only in showtime. Outside showtime they typically hold
`0`, `7FFFFE` or `C69A53`.

#### 9.3.2. `xdsl2LineStatusXtuTransSys` (X:006F19)

The value is the bit number (decimal) of the active transmission mode in
`Xdsl2TransmissionModeType` (RFC 5650, Section 4). It cannot be the bit mask itself:
the mask has more than 24 bits and VDSL2 is at bits 56–58 (`g9932AnnexA/B/C`). Values
used by this device class:

| Value | RFC 5650 bit name | Standard | Common name |
|---|---|---|---|
| 18 | `g9923PotsNonOverlapped` | G.992.3 Annex A | ADSL2 |
| 20 | `g9923IsdnNonOverlapped` | G.992.3 Annex B | ADSL2 |
| 40 | `g9925PotsNonOverlapped` | G.992.5 Annex A | ADSL2+ |
| 42 | `g9925IsdnNonOverlapped` | G.992.5 Annex B | ADSL2+ |
| 56 | `g9932AnnexA` | G.993.2 Annex A | VDSL2 |
| 57 | `g9932AnnexB` | G.993.2 Annex B | VDSL2 |

The value `57` has been observed on a VDSL2 line. Other values SHOULD be decoded with
the full RFC 5650 bit list. The value `0`
(`ansit1413`) is also the reset value of this register, so outside showtime `0` MUST
NOT be read as T1.413.

#### 9.3.3. `xdsl2LineStatusActProfile` (X:006F26), `xdsl2LConfProfProfiles` (X:007ABE)

Bit mask of VDSL2 profiles (`Xdsl2LineProfiles`, RFC 5650). `ActProfile` has exactly one
bit set (the active profile); `Profiles` contains the allowed profiles. Observed:
`ActProfile = 000040` on a 17a line.

| Bit | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| Profile | 8a | 8b | 8c | 8d | 12a | 12b | 17a | 30a |

#### 9.3.4. `nO_UsCombinationTpsTc` (X:001779), `nO_DsCombinationTpsTc` (X:001778)

| Value | TPS-TC |
|---|---|
| `000020` | PTM (observed) |
| `000040` | ATM |
| `000080` | STM |

#### 9.3.5. Other Enumerations

| Register | Values |
|---|---|
| `xdsl2LineStatusTrellis{Us,Ds}` (X:006FD3 / X:006FD2) | `1` true (observed in showtime, both directions), `2` false |
| `xdsl2LineStatusInitResult` (X:006F1B) | `0` noFail (observed in showtime), `1` configError, `2` configNotFeasible, `3` commFail, `4` noPeerAtu, `5` otherCause |
| `xdsl2LineStatusPwrMngState` (X:006F1A) | **Not maintained.** It reads `4` (L3, its reset value) also in showtime. A host MUST NOT report it. |
| `xdsl2LineStatusActSnrMode{Ds,Us}` (X:006F2D / X:006F2E) | `1` virtual noise disabled (observed in showtime), `2` virtual noise enabled. |

#### 9.3.6. Showtime Duration

`xdslMetanoiaShowtimeSeconds` (X:006D35) holds the time in seconds since the start of
the current showtime (observed in showtime shortly after synchronisation: `000027`,
39 s; later `00DD9F`, 56735 s). A host MAY report it as showtime uptime. Its value
outside showtime and its behaviour after 2^24 s (about 194 days) are not known
[UNVERIFIED]; a host SHOULD report it only while the line is in showtime and SHOULD treat
a decrease without a loss of showtime as a wrap (7.2).

### 9.4. Retrain Reasons

`xdsl2MetanoiaOtFailureReasons` (X:007F1C, valid on OT) /
`xdsl2MetanoiaRtFailureReasons` (X:007F59, valid on RT) hold the cause of the last loss
of showtime.

| Value | Cause |
|---|---|
| 1 | Near-end loss of signal (LoS) |
| 2 | Far-end loss of power (LoP) |
| 3 | CRC errors |
| 4 | Training failure (FRC TRN) |
| 5 | Disconnect |
| 6 | SNR below minimum |

A host SHOULD read the register of its own side right after the line leaves showtime.
The register keeps its value during the following showtime (observed: `1` in
showtime). The value `0` presumably means that no cause has been recorded (e.g. no loss
of showtime since start-up) [UNVERIFIED]; a host SHOULD report it as "none". Other
values not listed above SHOULD be reported as "unknown" together with the number.

### 9.5. Configuration Enumerations

| Register | Values |
|---|---|
| `xdsl2LConfProfUpboKLF` (X:007AE7) | Bits 0–1: `1` auto, `2` override, `3` UPBO disabled |
| `xdslRtxChConf{Ds,Us}RtxMode` | Bits 0–1: `0` forbidden, `1` preferred, `2` forced |
| `xdsl2LConfProfRaMode{Ds,Us}` (X:007A71 / X:007A72) | `1` manual, `2` raInit, `3` dynamicRa [UNVERIFIED] |
| `xdsl2LConfProfSnrMode{Ds,Us}` | `1` virtual noise disabled, `2` virtual noise enabled (as `xdsl2LineStatusActSnrMode`, 9.3.5). `0` is not a valid value. |
| `xdsl2LConfProfXdslMode` (X:007B0A) | `Xdsl2OperationModes` bit mask per RFC 5650 [UNVERIFIED] |

## 10. Device Modification (Out of Scope)

The protocol also provides requests that modify device memory, and the firmware offers
procedures built on them (e.g. line connect and disconnect, loop diagnostics,
configuration). This profile intentionally does not specify them. A monitoring host
MUST NOT send any request type other than CONNECT (`0x31`), READ (`0x01`) and
DISCONNECT (`0x50`), and Appendix A lists registers for reading only.

## 11. Monitoring Procedure

A monitoring host SHOULD proceed as follows:

1. Perform CONNECT (5.1).
2. Read the identification words and select the address layout (8.2).
3. Read the identification block (8.2, 6 words, including `xdslTerminal`) to detect a
   firmware change (6.4) and to determine OT/RT and the line state (9.2.1).
4. If the line is in showtime, read the status variables of interest (Appendix A.2,
   A.3, A.5; A.6 only as raw values, 7.3). Steps 3 and 4 SHOULD be combined into one multi-command READ (5.5),
   with the identification words first.
5. Repeat steps 3–4 periodically, observing the timing rules (6.3). Handle failures as
   described in 6.4; after a session error, continue with step 1.
6. When the line leaves showtime, read the retrain reason (9.4).

Typical status set per poll cycle on an RT device:

| Value | DS | US | Class |
|---|---|---|:---:|
| Actual data rate | `xdsl2ChStatusActDataRate2` | `xdsl2ChStatusActDataRate0` | M |
| Attainable rate | `xdsl2LineStatusAttainableRateDs` | `xdsl2LineStatusAttainableRateUs` | M |
| SNR margin | `xdsl2LineBandStatusSnrMargin10` | `xdsl2LineBandStatusSnrMargin9` | M |
| Signal attenuation | `xdsl2LineBandStatusSigAtten10` | per band: `xdsl2LineBandStatusSigAtten0`–`4` | M |
| Line attenuation | `xdsl2LineBandStatusLnAtten10` | per band: `xdsl2LineBandStatusLnAtten0`–`4` | M |
| Actual delay | `xdsl2ChStatusActDelay2` | `xdsl2ChStatusActDelay0` | M |
| Actual INP | `xdsl2ChStatusActInp2` | `xdsl2ChStatusActInp0` | M |
| Transmit power | `xdsl2LineStatusActAtpDs` | `xdsl2LineStatusActAtpUs` | M |
| CRC errors (this showtime) | `xdslMetanoiaRtCurrCodingViolations0` | `xdslMetanoiaRtCurrCodingViolations1` | C |
| Corrected blocks (this showtime) | `xdslMetanoiaRtCurrCorrectedBlocks0` | `xdslMetanoiaRtCurrCorrectedBlocks1` | C |
| Showtime duration | `xdslMetanoiaShowtimeSeconds` (9.3.6) | | C |

Upstream attenuation on an RT device: 9.1. Counter selection: 9.1. Value classes: 7.3.

All values in this table have been read on an RT device in showtime with plausible
results (9.1). Not confirmed are:

- the counting of CRC errors: `xdslMetanoiaRtCurrCodingViolations0`/`1` read 0 in all
  observations, so an increase has not been seen [UNVERIFIED];
- the meaning of a delay and INP of 0 when retransmission is in use (9.1)
  [UNVERIFIED].

## 12. Security Considerations

- The protocol has no authentication, integrity protection or encryption. Any station
  in the same layer-2 segment can read the complete DSP memory of the device and can
  also modify it with requests not covered by this profile.
- The CONNECT magic values are fixed constants and provide no security.
- The management port SHOULD be confined to a dedicated, trusted network segment.

---

## Appendix A. Register Reference

All registers are in space X. Columns:

- **Addr 1.60**: word address for firmware branch 1.60 (firmware `750202`, 8.2).
- **Addr 1.61**: address for firmware branch 1.61; `=` means identical, `–` means
  not present.
- **Words**: size of the variable in words. Multi-word variables are tables or text.
- **Class**: value class (7.3): `M` measurement, `C` counter, `S` snapshot count,
  `E` enumeration / bit mask / flag, `I` identification / text, `K` configuration, `–` other.
- **Type / Unit**: MIB type, value range and unit. Special values: Section 7.3.
  "**not maintained**" marks instances that the firmware does not update (9.1).
- **Description**: short note where needed; references point to Sections 8 and 9.
  Register names follow the VDSL2 line MIB (RFC 5650) where one exists.

### A.1. Identification and System

| Symbol | Addr 1.60 | Addr 1.61 | Words | Class | Type / Unit | Description |
|---|---|---|---:|:---:|---|---|
| `ModemStatus` | `00001D` | = | 1 | E |  | (see 9.2.2) |
| `xdslFirmwareVer` | `006C31` | = | 1 | I |  | (see 9.2.3) |
| `xdslFirmwareDate` | `006C32` | = | 1 | I | MMDDYY | (see 9.2.3) |
| `xdslFirmwareTime` | `006C33` | = | 1 | I | hhmmss | (see 9.2.3) |
| `xdslBoardType` | `006C34` | = | 1 | I |  | (see 8.2) |
| `xdslTerminal` | `006C35` | = | 1 | E |  | (see 9.2.1) |
| `xdslMetanoiaSignature` | `006C36` | = | 1 | I |  | (see 9.2.3) |
| `xdslTwConfig` | `006C39` | = | 1 | K |  |  |
| `xdslCfgHwConfig` | `006C3C` | = | 1 | K |  | (see 9.2.6) |
| `CfgM2MiiCtlReg` | `006C4E` | = | 1 | – |  |  |
| `CfgM2MiiCfgReg` | `006C4F` | = | 1 | – |  | (see 9.2.6) |
| `CfgM2UtpCfgReg` | `006C50` | = | 1 | – |  | (see 9.2.6) |
| `xdslTwConfig2` | `006D36` | = | 1 | K |  |  |
| `ModemErrBuf` | `006D53` | = | 32 | E |  | (see 9.2.2) |
| `ModemErrOvrflow` | `006D73` | = | 1 | E |  | (see 9.2.2) |
| `CfgPll1Ctl` | `006D80` | = | 1 | – |  | (see 9.2.6) |
| `CfgM2QosfrVd` | `006E36` | `006E4E` | 1 | – |  |  |
| `xdslTwConfig3` | `006E6F` | `006E87` | 1 | K |  | (see 9.2.4) |
| `xdslMetanoiaOtVcxo` | `007E72` | `007E87` | 1 | – |  | (see 9.2.7) |
| `xdslMetanoiaRtVcxo` | `007EAC` | `007EC1` | 1 | – |  | (see 9.2.7) |
| `Pll1Ctl` | `FFF70D` | = | 1 | – |  | (see 9.2.6) |
| `Miicr` | `FFFF94` | = | 1 | – |  | (see 9.2.6) |
| `Utpfr` | `FFFFA3` | = | 1 | – |  | (see 9.2.6) |

### A.2. Line Status

| Symbol | Addr 1.60 | Addr 1.61 | Words | Class | Type / Unit | Description |
|---|---|---|---:|:---:|---|---|
| `nO_DsCombinationTpsTc` | `001778` | `001775` | 1 | E |  | (see 9.3.4) |
| `nO_UsCombinationTpsTc` | `001779` | `001776` | 1 | E |  | (see 9.3.4) |
| `xdsl2LineStatusActAtpUs2` | `006D1F` | = | 1 | – |  |  |
| `xdsl2LineStatusActAtpDs2` | `006D20` | = | 1 | – |  |  |
| `VisibleUsPb0FirstTone` | `006E37` | `006E4F` | 1 | – |  |  |
| `VisibleUsPb0LastTone` | `006E38` | `006E50` | 1 | – |  |  |
| `VisibleUsPb1FirstTone` | `006E39` | `006E51` | 1 | – |  |  |
| `VisibleUsPb1LastTone` | `006E3A` | `006E52` | 1 | – |  |  |
| `VisibleUsPb2FirstTone` | `006E3B` | `006E53` | 1 | – |  |  |
| `VisibleUsPb2LastTone` | `006E3C` | `006E54` | 1 | – |  |  |
| `VisibleUsPb3FirstTone` | `006E3D` | `006E55` | 1 | – |  |  |
| `VisibleUsPb3LastTone` | `006E3E` | `006E56` | 1 | – |  |  |
| `VisibleUsPb4FirstTone` | `006E3F` | `006E57` | 1 | – |  |  |
| `VisibleUsPb4LastTone` | `006E40` | `006E58` | 1 | – |  |  |
| `VisibleDsPb0FirstTone` | `006E47` | `006E5F` | 1 | – |  |  |
| `VisibleDsPb0LastTone` | `006E48` | `006E60` | 1 | – |  |  |
| `VisibleDsPb1FirstTone` | `006E49` | `006E61` | 1 | – |  |  |
| `VisibleDsPb1LastTone` | `006E4A` | `006E62` | 1 | – |  |  |
| `VisibleDsPb2FirstTone` | `006E4B` | `006E63` | 1 | – |  |  |
| `VisibleDsPb2LastTone` | `006E4C` | `006E64` | 1 | – |  |  |
| `VisibleDsPb3FirstTone` | `006E4D` | `006E65` | 1 | – |  |  |
| `VisibleDsPb3LastTone` | `006E4E` | `006E66` | 1 | – |  |  |
| `xdsl2LineStatusXtuTransSys` | `006F19` | `006F2E` | 1 | E | Xdsl2TransmissionModeType | (see 9.3.2) |
| `xdsl2LineStatusPwrMngState` | `006F1A` | `006F2F` | 1 | E | Xdsl2PowerMngState | Line power management state (see 9.3.5) |
| `xdsl2LineStatusInitResult` | `006F1B` | `006F30` | 1 | E | Xdsl2InitResult | (see 9.3.5) |
| `xdsl2LineStatusAttainableRateDs` | `006F20` | `006F35` | 1 | M | Unsigned32 kbit/s |  |
| `xdsl2LineStatusAttainableRateUs` | `006F21` | `006F36` | 1 | M | Unsigned32 kbit/s |  |
| `xdsl2LineStatusActAtpDs` | `006F24` | `006F39` | 1 | M | Integer32 [-310..310] 0.1dBm | Actual aggregate transmit power downstream |
| `xdsl2LineStatusActAtpUs` | `006F25` | `006F3A` | 1 | M | Integer32 [-310..310] 0.1dBm | Actual aggregate transmit power upstream |
| `xdsl2LineStatusActProfile` | `006F26` | `006F3B` | 1 | E |  | (see 9.3.3) |
| `xdsl2LineStatusActSnrModeDs` | `006F2D` | `006F42` | 1 | E | Xdsl2LineSnrMode | Downstream virtual noise mode in use (see 9.3.5) |
| `xdsl2LineStatusActSnrModeUs` | `006F2E` | `006F43` | 1 | E | Xdsl2LineSnrMode | Upstream virtual noise mode in use (see 9.3.5) |
| `xdsl2LineStatusElectricalLength` | `006F2F` | `006F44` | 1 | M | Unsigned32 [0..1280] 0.1dB |  |
| `xdsl2LineStatusTrellisDs` | `006FD2` | `006FE7` | 1 | E | TruthValue | (see 9.3.5) |
| `xdsl2LineStatusTrellisUs` | `006FD3` | `006FE8` | 1 | E | TruthValue | (see 9.3.5) |
| `xdsl2LineBand0` | `006FD7` | `006FEC` | 1 | E | Xdsl2Band | (see 8.2) |
| `xdsl2LineBandStatusLnAtten0` | `006FD8` | `006FED` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSigAtten0` | `006FD9` | `006FEE` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSnrMargin0` | `006FDA` | `006FEF` | 1 | M | Integer32 [-640..630] 0.1dB |  |
| `xdsl2LineBand1` | `006FDB` | `006FF0` | 1 | E | Xdsl2Band | (see 8.2) |
| `xdsl2LineBandStatusLnAtten1` | `006FDC` | `006FF1` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSigAtten1` | `006FDD` | `006FF2` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSnrMargin1` | `006FDE` | `006FF3` | 1 | M | Integer32 [-640..630] 0.1dB |  |
| `xdsl2LineBand2` | `006FDF` | `006FF4` | 1 | E | Xdsl2Band | (see 8.2) |
| `xdsl2LineBandStatusLnAtten2` | `006FE0` | `006FF5` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSigAtten2` | `006FE1` | `006FF6` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSnrMargin2` | `006FE2` | `006FF7` | 1 | M | Integer32 [-640..630] 0.1dB |  |
| `xdsl2LineBand3` | `006FE3` | `006FF8` | 1 | E | Xdsl2Band | (see 8.2) |
| `xdsl2LineBandStatusLnAtten3` | `006FE4` | `006FF9` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSigAtten3` | `006FE5` | `006FFA` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSnrMargin3` | `006FE6` | `006FFB` | 1 | M | Integer32 [-640..630] 0.1dB |  |
| `xdsl2LineBand4` | `006FE7` | `006FFC` | 1 | E | Xdsl2Band | (see 8.2) |
| `xdsl2LineBandStatusLnAtten4` | `006FE8` | `006FFD` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSigAtten4` | `006FE9` | `006FFE` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSnrMargin4` | `006FEA` | `006FFF` | 1 | M | Integer32 [-640..630] 0.1dB |  |
| `xdsl2LineBand5` | `006FEB` | `007000` | 1 | E | Xdsl2Band | (see 8.2) |
| `xdsl2LineBandStatusLnAtten5` | `006FEC` | `007001` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSigAtten5` | `006FED` | `007002` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSnrMargin5` | `006FEE` | `007003` | 1 | M | Integer32 [-640..630] 0.1dB |  |
| `xdsl2LineBand6` | `006FEF` | `007004` | 1 | E | Xdsl2Band | (see 8.2) |
| `xdsl2LineBandStatusLnAtten6` | `006FF0` | `007005` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSigAtten6` | `006FF1` | `007006` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSnrMargin6` | `006FF2` | `007007` | 1 | M | Integer32 [-640..630] 0.1dB |  |
| `xdsl2LineBand7` | `006FF3` | `007008` | 1 | E | Xdsl2Band | (see 8.2) |
| `xdsl2LineBandStatusLnAtten7` | `006FF4` | `007009` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSigAtten7` | `006FF5` | `00700A` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSnrMargin7` | `006FF6` | `00700B` | 1 | M | Integer32 [-640..630] 0.1dB |  |
| `xdsl2LineBand8` | `006FF7` | `00700C` | 1 | E | Xdsl2Band | (see 8.2) |
| `xdsl2LineBandStatusLnAtten8` | `006FF8` | `00700D` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSigAtten8` | `006FF9` | `00700E` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSnrMargin8` | `006FFA` | `00700F` | 1 | M | Integer32 [-640..630] 0.1dB |  |
| `xdsl2LineBand9` | `006FFB` | `007010` | 1 | E | Xdsl2Band | (see 8.2) |
| `xdsl2LineBandStatusLnAtten9` | `006FFC` | `007011` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSigAtten9` | `006FFD` | `007012` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSnrMargin9` | `006FFE` | `007013` | 1 | M | Integer32 [-640..630] 0.1dB |  |
| `xdsl2LineBand10` | `006FFF` | `007014` | 1 | E | Xdsl2Band | (see 8.2) |
| `xdsl2LineBandStatusLnAtten10` | `007000` | `007015` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSigAtten10` | `007001` | `007016` | 1 | M | Unsigned32 [0..1270] 0.1dB |  |
| `xdsl2LineBandStatusSnrMargin10` | `007002` | `007017` | 1 | M | Integer32 [-640..630] 0.1dB |  |
| `xdsl2MetanoiaOtFailureReasons` | `007F1C` | `007F31` | 1 | E |  | (see 9.4) |
| `xdsl2MetanoiaRtFailureReasons` | `007F59` | `007F6E` | 1 | E |  | (see 9.4) |

### A.3. Channel Status

| Symbol | Addr 1.60 | Addr 1.61 | Words | Class | Type / Unit | Description |
|---|---|---|---:|:---:|---|---|
| `xdsl2ChStatusUnit0` | `007003` | `007018` | 1 | E | Xdsl2Unit | (see 8.2) |
| `xdsl2ChStatusActDataRate0` | `007004` | `007019` | 1 | M | Unsigned32 [0..200000] kbit/s |  |
| `xdsl2ChStatusPrevDataRate0` | `007005` | `00701A` | 1 | M | Unsigned32 [0..200000] kbit/s |  |
| `xdsl2ChStatusActDelay0` | `007006` | `00701B` | 1 | M | Unsigned32 [0..8176] ms |  |
| `xdsl2ChStatusActInp0` | `007007` | `00701C` | 1 | M | Unsigned32 [0..255] 0.1 symbols |  |
| `xdsl2ChStatusIntlvDepth0` | `00700C` | `007021` | 1 | M | Unsigned32 [1..4096] |  |
| `xdsl2ChStatusIntlvBlock0` | `00700D` | `007022` | 1 | M | Unsigned32 [4..255] |  |
| `xdsl2ChStatusUnit1` | `007011` | `007026` | 1 | E | Xdsl2Unit | (see 8.2) |
| `xdsl2ChStatusUnit2` | `00701F` | `007034` | 1 | E | Xdsl2Unit | (see 8.2) |
| `xdsl2ChStatusActDataRate2` | `007020` | `007035` | 1 | M | Unsigned32 [0..200000] kbit/s |  |
| `xdsl2ChStatusPrevDataRate2` | `007021` | `007036` | 1 | M | Unsigned32 [0..200000] kbit/s |  |
| `xdsl2ChStatusActDelay2` | `007022` | `007037` | 1 | M | Unsigned32 ms |  |
| `xdsl2ChStatusActInp2` | `007023` | `007038` | 1 | M | Unsigned32 [0..255] 0.1 symbols |  |
| `xdsl2ChStatusIntlvDepth2` | `007028` | `00703D` | 1 | M | Unsigned32 [1..4096] |  |
| `xdsl2ChStatusIntlvBlock2` | `007029` | `00703E` | 1 | M | Unsigned32 [4..255] |  |
| `xdsl2ChStatusUnit3` | `00702D` | `007042` | 1 | E | Xdsl2Unit | (see 8.2) |
| `xdsl2ChStatusActDataRate3` | `00702E` | `007043` | 1 | M | Unsigned32 [0..200000] kbit/s |  |
| `xdsl2ChStatusActDelay3` | `007030` | `007045` | 1 | M | Unsigned32 ms |  |
| `xdsl2ChStatusActInp3` | `007031` | `007046` | 1 | M | Unsigned32 [0..255] 0.1 symbols |  |

### A.4. Inventory

| Symbol | Addr 1.60 | Addr 1.61 | Words | Class | Type / Unit | Description |
|---|---|---|---:|:---:|---|---|
| `xdsl2LInvG994VendorId0` | `0079C8` | `0079DD` | 3 | I | OCTET STRING | G.994.1 vendor ID of the xTU-C (see 9.2.5) |
| `xdsl2LInvVersionNumber0` | `0079CE` | `0079E3` | 6 | I |  | Version number of the xTU-C (see 9.2.4) |
| `xdsl2LInvG994VendorId1` | `0079E4` | `0079F9` | 3 | I | OCTET STRING | G.994.1 vendor ID of the xTU-R (see 9.2.5) |
| `xdsl2LInvVersionNumber1` | `0079EA` | `0079FF` | 6 | I |  | Version number of the xTU-R (see 9.2.4) |
| `xdslGhsOtVendorId` | `007D98` | `007DAD` | 2 | I |  |  |
| `xdslGhsRtVendorId` | `007D9A` | `007DAF` | 2 | I |  |  |

### A.5. Performance Monitoring and Counters

| Symbol | Addr 1.60 | Addr 1.61 | Words | Class | Type / Unit | Description |
|---|---|---|---:|:---:|---|---|
| `xdslMetanoiaShowtimeSeconds` | `006D35` | = | 1 | C |  | (see 9.3.6) |
| `xdsl2PMLCurr15MTimeElapsed0` | `007C1F` | `007C34` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMLCurr15MFecs0` | `007C20` | `007C35` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr15MEs0` | `007C21` | `007C36` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr15MSes0` | `007C22` | `007C37` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr15MLoss0` | `007C23` | `007C38` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr15MUas0` | `007C24` | `007C39` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr1DayTimeElapsed0` | `007C27` | `007C3C` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMLCurr1DayFecs0` | `007C28` | `007C3D` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr1DayEs0` | `007C29` | `007C3E` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr1DaySes0` | `007C2A` | `007C3F` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr1DayLoss0` | `007C2B` | `007C40` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr1DayUas0` | `007C2C` | `007C41` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr15MTimeElapsed1` | `007C30` | `007C45` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMLCurr15MFecs1` | `007C31` | `007C46` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr15MEs1` | `007C32` | `007C47` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr15MSes1` | `007C33` | `007C48` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr15MLoss1` | `007C34` | `007C49` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr15MUas1` | `007C35` | `007C4A` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr1DayTimeElapsed1` | `007C38` | `007C4D` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMLCurr1DayFecs1` | `007C39` | `007C4E` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr1DayEs1` | `007C3A` | `007C4F` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr1DaySes1` | `007C3B` | `007C50` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr1DayLoss1` | `007C3C` | `007C51` | 1 | C | Counter32 |  |
| `xdsl2PMLCurr1DayUas1` | `007C3D` | `007C52` | 1 | C | Counter32 |  |
| `xdsl2PMLInitCurr15MTimeElapsed0` | `007C40` | `007C55` | 1 | C | Unsigned32 |  |
| `xdsl2PMLInitCurr15MFullInits0` | `007C41` | `007C56` | 1 | C | Unsigned32 |  |
| `xdsl2PMLInitCurr1DayTimeElapsed0` | `007C47` | `007C5C` | 1 | C | Unsigned32 |  |
| `xdsl2PMLInitCurr1DayFullInits0` | `007C48` | `007C5D` | 1 | C | Unsigned32 |  |
| `xdsl2PMLInitCurr15MTimeElapsed1` | `007C4E` | `007C63` | 1 | C | Unsigned32 |  |
| `xdsl2PMLInitCurr15MFullInits1` | `007C4F` | `007C64` | 1 | C | Unsigned32 |  |
| `xdsl2PMLInitCurr1DayTimeElapsed1` | `007C55` | `007C6A` | 1 | C | Unsigned32 |  |
| `xdsl2PMLInitCurr1DayFullInits1` | `007C56` | `007C6B` | 1 | C | Unsigned32 |  |
| `xdsl2PMLHist15MFecs0` | `007C5D` | `007C72` | 1 | S | Counter32 |  |
| `xdsl2PMLHist15MEs0` | `007C5E` | `007C73` | 1 | S | Counter32 |  |
| `xdsl2PMLHist15MSes0` | `007C5F` | `007C74` | 1 | S | Counter32 |  |
| `xdsl2PMLHist15MLoss0` | `007C60` | `007C75` | 1 | S | Counter32 |  |
| `xdsl2PMLHist15MUas0` | `007C61` | `007C76` | 1 | S | Counter32 |  |
| `xdsl2PMLHist15MFecs1` | `007C66` | `007C7B` | 1 | S | Counter32 |  |
| `xdsl2PMLHist15MEs1` | `007C67` | `007C7C` | 1 | S | Counter32 |  |
| `xdsl2PMLHist15MSes1` | `007C68` | `007C7D` | 1 | S | Counter32 |  |
| `xdsl2PMLHist15MLoss1` | `007C69` | `007C7E` | 1 | S | Counter32 |  |
| `xdsl2PMLHist15MUas1` | `007C6A` | `007C7F` | 1 | S | Counter32 |  |
| `xdsl2PMLHist1DFecs0` | `007C6F` | `007C84` | 1 | S | Counter32 |  |
| `xdsl2PMLHist1DEs0` | `007C70` | `007C85` | 1 | S | Counter32 |  |
| `xdsl2PMLHist1DSes0` | `007C71` | `007C86` | 1 | S | Counter32 |  |
| `xdsl2PMLHist1DLoss0` | `007C72` | `007C87` | 1 | S | Counter32 |  |
| `xdsl2PMLHist1DUas0` | `007C73` | `007C88` | 1 | S | Counter32 |  |
| `xdsl2PMLHist1DFecs1` | `007C78` | `007C8D` | 1 | S | Counter32 |  |
| `xdsl2PMLHist1DEs1` | `007C79` | `007C8E` | 1 | S | Counter32 |  |
| `xdsl2PMLHist1DSes1` | `007C7A` | `007C8F` | 1 | S | Counter32 |  |
| `xdsl2PMLHist1DLoss1` | `007C7B` | `007C90` | 1 | S | Counter32 |  |
| `xdsl2PMLHist1DUas1` | `007C7C` | `007C91` | 1 | S | Counter32 |  |
| `xdsl2PMLHistInit15MFullInits0` | `007C80` | `007C95` | 1 | S | Unsigned32 |  |
| `xdsl2PMLHistInit15MFullInits1` | `007C87` | `007C9C` | 1 | S | Unsigned32 |  |
| `xdsl2PMLHistInit1DFullInits0` | `007C8E` | `007CA3` | 1 | S | Unsigned32 |  |
| `xdsl2PMLHistInit1DFullInits1` | `007C95` | `007CAA` | 1 | S | Unsigned32 |  |
| `xdsl2PMChCurr15MTimeElapsed0` | `007C9D` | `007CB2` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMChCurr15MCodingViolations0` | `007C9E` | `007CB3` | 1 | C | Unsigned32 |  |
| `xdsl2PMChCurr15MCorrectedBlocks0` | `007C9F` | `007CB4` | 1 | C | Unsigned32 |  |
| `xdsl2PMChCurr1DayTimeElapsed0` | `007CA2` | `007CB7` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMChCurr1DayCodingViolations0` | `007CA3` | `007CB8` | 1 | C | Unsigned32 |  |
| `xdsl2PMChCurr1DayCorrectedBlocks0` | `007CA4` | `007CB9` | 1 | C | Unsigned32 |  |
| `xdsl2PMChCurr15MTimeElapsed1` | `007CA8` | `007CBD` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMChCurr1DayTimeElapsed1` | `007CAD` | `007CC2` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMChCurr15MTimeElapsed2` | `007CB3` | `007CC8` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMChCurr15MCodingViolations2` | `007CB4` | `007CC9` | 1 | C | Unsigned32 |  |
| `xdsl2PMChCurr15MCorrectedBlocks2` | `007CB5` | `007CCA` | 1 | C | Unsigned32 |  |
| `xdsl2PMChCurr1DayTimeElapsed2` | `007CB8` | `007CCD` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMChCurr1DayCodingViolations2` | `007CB9` | `007CCE` | 1 | C | Unsigned32 |  |
| `xdsl2PMChCurr1DayCorrectedBlocks2` | `007CBA` | `007CCF` | 1 | C | Unsigned32 |  |
| `xdsl2PMChCurr15MTimeElapsed3` | `007CBE` | `007CD3` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMChCurr1DayTimeElapsed3` | `007CC3` | `007CD8` | 1 | C | HCPerfTimeElapsed |  |
| `xdsl2PMChHist15MCodingViolations0` | `007CC9` | `007CDE` | 1 | S | Unsigned32 |  |
| `xdsl2PMChHist15MCorrectedBlocks0` | `007CCA` | `007CDF` | 1 | S | Unsigned32 |  |
| `xdsl2PMChHist15MCodingViolations2` | `007CD5` | `007CEA` | 1 | S | Unsigned32 |  |
| `xdsl2PMChHist15MCorrectedBlocks2` | `007CD6` | `007CEB` | 1 | S | Unsigned32 |  |
| `xdsl2PMChHist1DCodingViolations0` | `007CE1` | `007CF6` | 1 | S | Unsigned32 |  |
| `xdsl2PMChHist1DCorrectedBlocks0` | `007CE2` | `007CF7` | 1 | S | Unsigned32 |  |
| `xdsl2PMChHist1DCodingViolations2` | `007CED` | `007D02` | 1 | S | Unsigned32 |  |
| `xdsl2PMChHist1DCorrectedBlocks2` | `007CEE` | `007D03` | 1 | S | Unsigned32 |  |
| `xdslMetanoiaOtInits` | `007E74` | `007E89` | 1 | C |  |  |
| `xdslMetanoiaOtRxPktCntr` | `007E76` | `007E8B` | 1 | C |  |  |
| `xdslMetanoiaOtTxPktCntr` | `007E77` | `007E8C` | 1 | C |  |  |
| `xdslMetanoiaRtInits` | `007EAE` | `007EC3` | 1 | C |  |  |
| `xdslMetanoiaRtRxPktCntr` | `007EB0` | `007EC5` | 1 | C |  |  |
| `xdslMetanoiaRtTxPktCntr` | `007EB1` | `007EC6` | 1 | C |  |  |
| `xdslMetanoiaOtCorrectedBlocks0` | `007EE0` | `007EF5` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtCodingViolations0` | `007EE1` | `007EF6` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtFecs0` | `007EE2` | `007EF7` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtEs0` | `007EE3` | `007EF8` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtSes0` | `007EE4` | `007EF9` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtLoss0` | `007EE5` | `007EFA` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtUas0` | `007EE6` | `007EFB` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtCurrCorrectedBlocks0` | `007EEA` | `007EFF` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtCurrCodingViolations0` | `007EEB` | `007F00` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtCurrFecs0` | `007EEC` | `007F01` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtCurrEs0` | `007EED` | `007F02` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtCurrSes0` | `007EEE` | `007F03` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtCurrLoss0` | `007EEF` | `007F04` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtCurrUas0` | `007EF0` | `007F05` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtLastSecCorrectedBlocks0` | `007EF4` | `007F09` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaOtLastSecCodingViolations0` | `007EF5` | `007F0A` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaOtLastSecFecs0` | `007EF6` | `007F0B` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaOtLastSecEs0` | `007EF7` | `007F0C` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaOtLastSecSes0` | `007EF8` | `007F0D` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaOtLastSecLoss0` | `007EF9` | `007F0E` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaOtLastSecUas0` | `007EFA` | `007F0F` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaOtCorrectedBlocks1` | `007EFE` | `007F13` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtCodingViolations1` | `007EFF` | `007F14` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtFecs1` | `007F00` | `007F15` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtEs1` | `007F01` | `007F16` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtSes1` | `007F02` | `007F17` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtLoss1` | `007F03` | `007F18` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtUas1` | `007F04` | `007F19` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtCurrCorrectedBlocks1` | `007F08` | `007F1D` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtCurrCodingViolations1` | `007F09` | `007F1E` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaOtCurrFecs1` | `007F0A` | `007F1F` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtCurrEs1` | `007F0B` | `007F20` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtCurrSes1` | `007F0C` | `007F21` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtCurrLoss1` | `007F0D` | `007F22` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtCurrUas1` | `007F0E` | `007F23` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtLastSecCorrectedBlocks1` | `007F12` | `007F27` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaOtLastSecCodingViolations1` | `007F13` | `007F28` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaOtLastSecFecs1` | `007F14` | `007F29` | 1 | S | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtLastSecEs1` | `007F15` | `007F2A` | 1 | S | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtLastSecSes1` | `007F16` | `007F2B` | 1 | S | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtLastSecLoss1` | `007F17` | `007F2C` | 1 | S | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaOtLastSecUas1` | `007F18` | `007F2D` | 1 | S | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtCorrectedBlocks0` | `007F1D` | `007F32` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtCodingViolations0` | `007F1E` | `007F33` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtFecs0` | `007F1F` | `007F34` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtEs0` | `007F20` | `007F35` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtSes0` | `007F21` | `007F36` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtLoss0` | `007F22` | `007F37` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtUas0` | `007F23` | `007F38` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtCurrCorrectedBlocks0` | `007F27` | `007F3C` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtCurrCodingViolations0` | `007F28` | `007F3D` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtCurrFecs0` | `007F29` | `007F3E` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtCurrEs0` | `007F2A` | `007F3F` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtCurrSes0` | `007F2B` | `007F40` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtCurrLoss0` | `007F2C` | `007F41` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtCurrUas0` | `007F2D` | `007F42` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtLastSecCorrectedBlocks0` | `007F31` | `007F46` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaRtLastSecCodingViolations0` | `007F32` | `007F47` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaRtLastSecFecs0` | `007F33` | `007F48` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaRtLastSecEs0` | `007F34` | `007F49` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaRtLastSecSes0` | `007F35` | `007F4A` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaRtLastSecLoss0` | `007F36` | `007F4B` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaRtLastSecUas0` | `007F37` | `007F4C` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaRtCorrectedBlocks1` | `007F3B` | `007F50` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtCodingViolations1` | `007F3C` | `007F51` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtFecs1` | `007F3D` | `007F52` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtEs1` | `007F3E` | `007F53` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtSes1` | `007F3F` | `007F54` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtLoss1` | `007F40` | `007F55` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtUas1` | `007F41` | `007F56` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtCurrCorrectedBlocks1` | `007F45` | `007F5A` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtCurrCodingViolations1` | `007F46` | `007F5B` | 1 | C |  | (see 9.1) |
| `xdslMetanoiaRtCurrFecs1` | `007F47` | `007F5C` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtCurrEs1` | `007F48` | `007F5D` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtCurrSes1` | `007F49` | `007F5E` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtCurrLoss1` | `007F4A` | `007F5F` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtCurrUas1` | `007F4B` | `007F60` | 1 | C | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtLastSecCorrectedBlocks1` | `007F4F` | `007F64` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaRtLastSecCodingViolations1` | `007F50` | `007F65` | 1 | S |  | (see 9.1) |
| `xdslMetanoiaRtLastSecFecs1` | `007F51` | `007F66` | 1 | S | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtLastSecEs1` | `007F52` | `007F67` | 1 | S | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtLastSecSes1` | `007F53` | `007F68` | 1 | S | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtLastSecLoss1` | `007F54` | `007F69` | 1 | S | **not maintained** (see 9.1) | (see 9.1) |
| `xdslMetanoiaRtLastSecUas1` | `007F55` | `007F6A` | 1 | S | **not maintained** (see 9.1) | (see 9.1) |

### A.6. G.INP / Retransmission

| Symbol | Addr 1.60 | Addr 1.61 | Words | Class | Type / Unit | Description |
|---|---|---|---:|:---:|---|---|
| `xdslRtxChConfDsRtxMode` | `007F5B` | `007F70` | 1 | K |  | (see 9.5) |
| `xdslRtxChConfUsRtxMode` | `007F5C` | `007F71` | 1 | K |  | (see 9.5) |
| `xdslRtxChConfDsMinEtrRtx` | `007F5D` | `007F72` | 1 | K |  |  |
| `xdslRtxChConfUsMinEtrRtx` | `007F5E` | `007F73` | 1 | K |  |  |
| `xdslRtxChConfDsMaxEtrRtx` | `007F5F` | `007F74` | 1 | K |  |  |
| `xdslRtxChConfUsMaxEtrRtx` | `007F60` | `007F75` | 1 | K |  |  |
| `xdslRtxChConfDsMaxNdrRtx` | `007F61` | `007F76` | 1 | K |  |  |
| `xdslRtxChConfUsMaxNdrRtx` | `007F62` | `007F77` | 1 | K |  |  |
| `xdslRtxChConfDsDelayMaxRtx` | `007F63` | `007F78` | 1 | K |  |  |
| `xdslRtxChConfUsDelayMaxRtx` | `007F64` | `007F79` | 1 | K |  |  |
| `xdslRtxChConfDsDelayMinRtx` | `007F65` | `007F7A` | 1 | K |  |  |
| `xdslRtxChConfUsDelayMinRtx` | `007F66` | `007F7B` | 1 | K |  |  |
| `xdslRtxChConfDsInpMinShineRtx` | `007F67` | `007F7C` | 1 | K |  |  |
| `xdslRtxChConfUsInpMinShineRtx` | `007F68` | `007F7D` | 1 | K |  |  |
| `xdslRtxChConfDsInpMin8ShineRtx` | `007F69` | `007F7E` | 1 | K |  |  |
| `xdslRtxChConfUsInpMin8ShineRtx` | `007F6A` | `007F7F` | 1 | K |  |  |
| `xdslRtxChConfDsInpShineRatioRtx` | `007F6B` | `007F80` | 1 | K |  |  |
| `xdslRtxChConfUsInpShineRatioRtx` | `007F6C` | `007F81` | 1 | K |  |  |
| `xdslRtxChConfDsInpMinReinRtx` | `007F6D` | `007F82` | 1 | K |  |  |
| `xdslRtxChConfUsInpMinReinRtx` | `007F6E` | `007F83` | 1 | K |  |  |
| `xdslRtxChConfDsInpMin8ReinRtx` | `007F6F` | `007F84` | 1 | K |  |  |
| `xdslRtxChConfUsInpMin8ReinRtx` | `007F70` | `007F85` | 1 | K |  |  |
| `xdslRtxChConfDsIatReinRtx` | `007F71` | `007F86` | 1 | K |  |  |
| `xdslRtxChConfUsIatReinRtx` | `007F72` | `007F87` | 1 | K |  |  |
| `xdslRtxChConfDsLeftrThresh` | `007F73` | `007F88` | 1 | K |  |  |
| `xdslRtxChConfUsLeftrThresh` | `007F74` | `007F89` | 1 | K |  |  |
| `xdslRtxChStatusOtUnit` | `007F75` | `007F8A` | 1 | E |  |  |
| `xdslRtxChStatusOtRtxUsed` | `007F76` | `007F8B` | 1 | E |  |  |
| `xdslRtxChStatusOtEtr` | `007F77` | `007F8C` | 1 | – |  |  |
| `xdslRtxChStatusOtEftr` | `007F78` | `007F8D` | 1 | – |  |  |
| `xdslRtxChStatusOtEftrMin` | `007F79` | `007F8E` | 1 | – |  |  |
| `xdslRtxChStatusOtActInpShine` | `007F7A` | `007F8F` | 1 | – |  |  |
| `xdslRtxChStatusOtActInpRein` | `007F7B` | `007F90` | 1 | – |  |  |
| `xdslRtxChStatusOtActDelayRtx` | `007F7C` | `007F91` | 1 | – |  |  |
| `xdslRtxChStatusOtLeftrsHi` | `007F7D` | `007F92` | 1 | C |  |  |
| `xdslRtxChStatusOtLeftrsLo` | `007F7E` | `007F93` | 1 | C |  |  |
| `xdslRtxChStatusOtErrorFreeBitsHi` | `007F7F` | `007F94` | 1 | C |  |  |
| `xdslRtxChStatusOtErrorFreeBitsLo` | `007F80` | `007F95` | 1 | C |  |  |
| `xdslRtxChStatusOtRtxUc` | `007F81` | `007F96` | 1 | C |  |  |
| `xdslRtxChStatusOtRtxC` | `007F82` | `007F97` | 1 | C |  |  |
| `xdslRtxChStatusOtRtxTx` | `007F83` | `007F98` | 1 | C |  |  |
| `xdslRtxChStatusOtRtxSupport` | `007F84` | `007F99` | 1 | E |  |  |
| `xdslRtxChStatusOtActNdr` | `007F85` | `007F9A` | 1 | – |  |  |
| `xdslRtxChStatusOtPreviousEtr` | `007F86` | `007F9B` | 1 | – |  |  |
| `xdslRtxChStatusRtUnit` | `007F8B` | `007FA0` | 1 | E |  |  |
| `xdslRtxChStatusRtRtxUsed` | `007F8C` | `007FA1` | 1 | E |  |  |
| `xdslRtxChStatusRtEtr` | `007F8D` | `007FA2` | 1 | – |  |  |
| `xdslRtxChStatusRtEftr` | `007F8E` | `007FA3` | 1 | – |  |  |
| `xdslRtxChStatusRtEftrMin` | `007F8F` | `007FA4` | 1 | – |  |  |
| `xdslRtxChStatusRtActInpShine` | `007F90` | `007FA5` | 1 | – |  |  |
| `xdslRtxChStatusRtActInpRein` | `007F91` | `007FA6` | 1 | – |  |  |
| `xdslRtxChStatusRtActDelayRtx` | `007F92` | `007FA7` | 1 | – |  |  |
| `xdslRtxChStatusRtLeftrsHi` | `007F93` | `007FA8` | 1 | C |  |  |
| `xdslRtxChStatusRtLeftrsLo` | `007F94` | `007FA9` | 1 | C |  |  |
| `xdslRtxChStatusRtErrorFreeBitsHi` | `007F95` | `007FAA` | 1 | C |  |  |
| `xdslRtxChStatusRtErrorFreeBitsLo` | `007F96` | `007FAB` | 1 | C |  |  |
| `xdslRtxChStatusRtRtxUc` | `007F97` | `007FAC` | 1 | C |  |  |
| `xdslRtxChStatusRtRtxC` | `007F98` | `007FAD` | 1 | C |  |  |
| `xdslRtxChStatusRtRtxTx` | `007F99` | `007FAE` | 1 | C |  |  |
| `xdslRtxChStatusRtRtxSupport` | `007F9A` | `007FAF` | 1 | E |  |  |
| `xdslRtxChStatusRtActNdr` | `007F9B` | `007FB0` | 1 | – |  |  |
| `xdslRtxChStatusRtPreviousEtr` | `007F9C` | `007FB1` | 1 | – |  |  |

### A.7. Diagnostics

| Symbol | Addr 1.60 | Addr 1.61 | Words | Class | Type / Unit | Description |
|---|---|---|---:|:---:|---|---|
| `xdsl2SCStatusSegment` | `007070` | `007085` | 1 | – | Unsigned32 [1..8] |  |
| `xdsl2SCStatusSegmentLog` | `007471` | `007486` | 512 | – | OCTET STRING [0..512] dB |  |
| `xdsl2SCStatusSegmentQln` | `007671` | `007686` | 171 | – | OCTET STRING [0..512] dBm/Hz |  |
| `xdsl2SCStatusSegmentSnr` | `00771C` | `007731` | 171 | – | OCTET STRING [0..512] 0.5dB |  |
| `xdsl2SCStatusSegmentBitsGainAlloc` | `0077C7` | `0077DC` | 512 | – | OCTET STRING [0..512] |  |

### A.8. Configuration

| Symbol | Addr 1.60 | Addr 1.61 | Words | Class | Type / Unit | Description |
|---|---|---|---:|:---:|---|---|
| `xdslMetanoiaUs0PsdLimit` | `006D2B` | = | 1 | K |  |  |
| `xdslVdsl2ProfilesLimit8a` | `006D2C` | = | 1 | K |  |  |
| `xdslVdsl2ProfilesLimit8b` | `006D2D` | = | 1 | K |  |  |
| `xdslVdsl2ProfilesLimit8c` | `006D2E` | = | 1 | K |  |  |
| `xdslVdsl2ProfilesLimit8d` | `006D2F` | = | 1 | K |  |  |
| `xdslVdsl2ProfilesLimit12a` | `006D30` | = | 1 | K |  |  |
| `xdslVdsl2ProfilesLimit12b` | `006D31` | = | 1 | K |  |  |
| `xdslVdsl2ProfilesLimit17a` | `006D32` | = | 1 | K |  |  |
| `xdslVdsl2ProfilesLimit30a` | `006D33` | = | 1 | K |  |  |
| `xdslCfgIopFixMeta0` | `006E7E` | `006E96` | 1 | K |  |  |
| `xdslCfgIopFixMeta1` | `006E7F` | `006E97` | 1 | K |  |  |
| `xdslCfgIopFixMeta2` | `006E80` | `006E98` | 1 | K |  |  |
| `xdslCfgIopFixMeta3` | `006E81` | `006E99` | 1 | K |  |  |
| `xdslCfgIopFixBrcm0` | `006E82` | `006E9A` | 1 | K |  |  |
| `xdslCfgIopFixBrcm1` | `006E83` | `006E9B` | 1 | K |  |  |
| `xdslCfgIopFixBrcm2` | `006E84` | `006E9C` | 1 | K |  |  |
| `xdslCfgIopFixBrcm3` | `006E85` | `006E9D` | 1 | K |  |  |
| `xdslCfgIopFixIkns0` | `006E86` | `006E9E` | 1 | K |  |  |
| `xdslCfgIopFixIkns1` | `006E87` | `006E9F` | 1 | K |  |  |
| `xdslCfgIopFixIkns2` | `006E88` | `006EA0` | 1 | K |  |  |
| `xdslCfgIopFixIkns3` | `006E89` | `006EA1` | 1 | K |  |  |
| `xdslCfgIopFixLantiq0` | `006E8A` | `006EA2` | 1 | K |  |  |
| `xdslCfgIopFixLantiq1` | `006E8B` | `006EA3` | 1 | K |  |  |
| `xdslCfgIopFixLantiq2` | `006E8C` | `006EA4` | 1 | K |  |  |
| `xdslCfgIopFixLantiq3` | `006E8D` | `006EA5` | 1 | K |  |  |
| `xdslCfgIopFixReserved0` | `006E8E` | `006EA6` | 1 | K |  |  |
| `xdslCfgIopFixReserved1` | `006E8F` | `006EA7` | 1 | K |  |  |
| `xdslCfgIopFixReserved2` | `006E90` | `006EA8` | 1 | K |  |  |
| `xdslCfgIopFixReserved3` | `006E91` | `006EA9` | 1 | K |  |  |
| `xdslCfgIopFixReserved4` | `006E92` | `006EAA` | 1 | K |  |  |
| `xdslCfgTargetTrainTimeOut1` | `006E9E` | `006EB6` | 1 | K |  |  |
| `xdslCfgTargetTrainTimeOut2` | `006E9F` | `006EB7` | 1 | K |  |  |
| `xdslCfgTargetTrainTimeOut3` | `006EA0` | `006EB8` | 1 | K |  |  |
| `xdslCfgIopFixTopLvlCtrl0` | `006EA6` | `006EBE` | 1 | K |  |  |
| `xdslCfgIopFixTopLvlCtrl1` | `006EA7` | `006EBF` | 1 | K |  |  |
| `xdslCfgIopFixTopLvlCtrl2` | `006EA8` | `006EC0` | 1 | K |  |  |
| `xdslCfgIopFixTopLvlCtrl3` | `006EA9` | `006EC1` | 1 | K |  |  |
| `xdslCfgIopFixTopLvlMaxUsTones` | `006EAA` | `006EC2` | 1 | K |  |  |
| `xdslCfgIopFixReserved5` | – | `006EAB` | 1 | K |  |  |
| `xdslCfgIopFixTopLvlMaxDsTones` | `006EAB` | `006EC3` | 1 | K |  |  |
| `xdslCfgIopFixReserved6` | – | `006EAC` | 1 | K |  |  |
| `xdslCfgIopFixTopLvlMaxUsRate` | `006EAC` | `006EC4` | 1 | K |  |  |
| `xdslCfgIopFixReserved7` | – | `006EAD` | 1 | K |  |  |
| `xdslCfgIopFixTopLvlMaxDsRate` | `006EAD` | `006EC5` | 1 | K |  |  |
| `xdslCfgIopFixReserved8` | – | `006EAE` | 1 | K |  |  |
| `xdslCfgIopFixReserved9` | – | `006EAF` | 1 | K |  |  |
| `xdslCfgIopFixReserved10` | – | `006EB0` | 1 | K |  |  |
| `xdsl2LConfProfVdsl2CarMask` | `007A11` | `007A26` | 64 | K |  |  |
| `xdsl2LConfProfRfiBands` | `007A51` | `007A66` | 32 | K | Xdsl2RfiBands |  |
| `xdsl2LConfProfRaModeDs` | `007A71` | `007A86` | 1 | K | Xdsl2RaMode | Downstream rate adaptation mode (see 9.5) |
| `xdsl2LConfProfRaModeUs` | `007A72` | `007A87` | 1 | K | Xdsl2RaMode | Upstream rate adaptation mode (see 9.5) |
| `xdsl2LConfProfRaUsNrmDs` | `007A73` | `007A88` | 1 | K | Unsigned32 [0..310] 0.1dB |  |
| `xdsl2LConfProfRaUsNrmUs` | `007A74` | `007A89` | 1 | K | Unsigned32 [0..310] 0.1dB |  |
| `xdsl2LConfProfRaUsTimeDs` | `007A75` | `007A8A` | 1 | K | Unsigned32 [0..16383] s |  |
| `xdsl2LConfProfRaUsTimeUs` | `007A76` | `007A8B` | 1 | K | Unsigned32 [0..16383] s |  |
| `xdsl2LConfProfRaDsNrmDs` | `007A77` | `007A8C` | 1 | K | Unsigned32 [0..310] 0.1dB |  |
| `xdsl2LConfProfRaDsNrmUs` | `007A78` | `007A8D` | 1 | K | Unsigned32 [0..310] 0.1dB |  |
| `xdsl2LConfProfRaDsTimeDs` | `007A79` | `007A8E` | 1 | K | Unsigned32 [0..16383] s |  |
| `xdsl2LConfProfRaDsTimeUs` | `007A7A` | `007A8F` | 1 | K | Unsigned32 [0..16383] s |  |
| `xdsl2LConfProfTargetSnrmDs` | `007A7B` | `007A90` | 1 | K | Unsigned32 [0..310] 0.1dB |  |
| `xdsl2LConfProfTargetSnrmUs` | `007A7C` | `007A91` | 1 | K | Unsigned32 [0..310] 0.1dB |  |
| `xdsl2LConfProfMaxSnrmDs` | `007A7D` | `007A92` | 1 | K | Unsigned32 [0..310] 0.1dB |  |
| `xdsl2LConfProfMaxSnrmUs` | `007A7E` | `007A93` | 1 | K | Unsigned32 [0..310] 0.1dB |  |
| `xdsl2LConfProfMinSnrmDs` | `007A7F` | `007A94` | 1 | K | Unsigned32 [0..310] 0.1dB |  |
| `xdsl2LConfProfMinSnrmUs` | `007A80` | `007A95` | 1 | K | Unsigned32 [0..310] 0.1dB |  |
| `xdsl2LConfProfMsgMinUs` | `007A81` | `007A96` | 1 | K | Unsigned32 [4..248] kbit/s |  |
| `xdsl2LConfProfMsgMinDs` | `007A82` | `007A97` | 1 | K | Unsigned32 [4..248] kbit/s |  |
| `xdsl2LConfProfSnrModeDs` | `007A84` | `007A99` | 1 | K | Xdsl2LineSnrMode | Enables the transmitter referred virtual noise in the downstream direction (see 9.5) |
| `xdsl2LConfProfSnrModeUs` | `007A85` | `007A9A` | 1 | K | Xdsl2LineSnrMode | Enables the transmitter referred virtual noise in the upstream direction (see 9.5) |
| `xdsl2LConfProfTxRefVnDs` | `007A86` | `007A9B` | 32 | K | Xdsl2LineTxRefVnDs |  |
| `xdsl2LConfProfTxRefVnUs` | `007AA6` | `007ABB` | 16 | K | Xdsl2LineTxRefVnUs |  |
| `xdsl2LConfProfProfiles` | `007ABE` | `007AD3` | 1 | K | Xdsl2LineProfiles | (see 9.3.3) |
| `xdsl2LConfProfDpboEPsd` | `007ABF` | `007AD4` | 32 | K | Xdsl2PsdMaskDs |  |
| `xdsl2LConfProfDpboEsEL` | `007ADF` | `007AF4` | 1 | K | Unsigned32 [0..511] 0.5dB |  |
| `xdsl2LConfProfDpboEsCableModelA` | `007AE0` | `007AF5` | 1 | K | Unsigned32 [0..640] 2^-8 |  |
| `xdsl2LConfProfDpboEsCableModelB` | `007AE1` | `007AF6` | 1 | K | Unsigned32 [0..640] 2^-8 |  |
| `xdsl2LConfProfDpboEsCableModelC` | `007AE2` | `007AF7` | 1 | K | Unsigned32 [0..640] 2^-8 |  |
| `xdsl2LConfProfDpboMus` | `007AE3` | `007AF8` | 1 | K | Unsigned32 [0..255] 0.5dBm/Hz |  |
| `xdsl2LConfProfDpboFMin` | `007AE4` | `007AF9` | 1 | K | Unsigned32 [0..2048] 4.3125kHz |  |
| `xdsl2LConfProfDpboFMax` | `007AE5` | `007AFA` | 1 | K | Unsigned32 [32..6956] 4.3125kHz |  |
| `xdsl2LConfProfUpboKL` | `007AE6` | `007AFB` | 1 | K | Unsigned32 [0..1280] 0.1dB |  |
| `xdsl2LConfProfUpboKLF` | `007AE7` | `007AFC` | 1 | K | Xdsl2UpboKLF | (see 9.5) |
| `xdsl2LConfProfBandDs` | `007AF4` | `007B09` | 10 | K |  |  |
| `xdsl2LConfProfBandUs` | `007AFE` | `007B13` | 10 | K |  |  |
| `xdsl2LConfProfXdslMode` | `007B0A` | `007B1F` | 1 | K | Xdsl2OperationModes | (see 9.5) |
| `xdsl2LConfProfMaxNomPsdDs` | `007B0B` | `007B20` | 1 | K | Integer32 [-600..-300] 0.1dBm/Hz |  |
| `xdsl2LConfProfMaxNomPsdUs` | `007B0C` | `007B21` | 1 | K | Integer32 [-600..-300] 0.1dBm/Hz |  |
| `xdsl2LConfProfMaxNomAtpDs` | `007B0D` | `007B22` | 1 | K | Unsigned32 [0..255] 0.1dBm |  |
| `xdsl2LConfProfMaxNomAtpUs` | `007B0E` | `007B23` | 1 | K | Unsigned32 [0..255] 0.1dBm |  |
| `xdsl2LConfProfPsdMaskDs` | `007B10` | `007B25` | 40 | K | bits 23–16: PSD level (−0.5 dBm/Hz steps), bits 15–0: tone index |  |
| `xdsl2LConfProfPsdMaskUs` | `007B38` | `007B4D` | 40 | K | bits 23–16: PSD level (−0.5 dBm/Hz steps), bits 15–0: tone index |  |
| `xdsl2LConfProfPsdMaskSelectUs` | `007B60` | `007B75` | 1 | K |  |  |
| `xdsl2LConfProfClassMask` | `007B61` | `007B76` | 1 | K |  |  |
| `xdsl2LConfProfLimitMaskDs` | `007B6B` | `007B80` | 40 | K | bits 23–16: PSD level (−0.5 dBm/Hz steps), bits 15–0: tone index |  |
| `xdsl2LConfProfLimitMaskUs` | `007B93` | `007BA8` | 40 | K | bits 23–16: PSD level (−0.5 dBm/Hz steps), bits 15–0: tone index |  |
| `xdsl2LConfProfUpboPsdA0` | `007BBC` | `007BD1` | 1 | K | Integer32 [4000..8095] 0.01dBm/Hz |  |
| `xdsl2LConfProfUpboPsdB0` | `007BBD` | `007BD2` | 1 | K | Integer32 [0..4095] 0.01dBm/Hz |  |
| `xdsl2LConfProfUpboPsdA1` | `007BC1` | `007BD6` | 1 | K | Integer32 [4000..8095] 0.01dBm/Hz |  |
| `xdsl2LConfProfUpboPsdB1` | `007BC2` | `007BD7` | 1 | K | Integer32 [0..4095] 0.01dBm/Hz |  |
| `xdsl2LConfProfUpboPsdA2` | `007BC6` | `007BDB` | 1 | K | Integer32 [4000..8095] 0.01dBm/Hz |  |
| `xdsl2LConfProfUpboPsdB2` | `007BC7` | `007BDC` | 1 | K | Integer32 [0..4095] 0.01dBm/Hz |  |
| `xdsl2LConfProfUpboPsdA3` | `007BCB` | `007BE0` | 1 | K | Integer32 [4000..8095] 0.01dBm/Hz |  |
| `xdsl2LConfProfUpboPsdB3` | `007BCC` | `007BE1` | 1 | K | Integer32 [0..4095] 0.01dBm/Hz |  |
| `xdsl2ChConfProfMinDataRateDs0` | `007BD0` | `007BE5` | 1 | K | Unsigned32 [0..200000] kbit/s |  |
| `xdsl2ChConfProfMinDataRateUs0` | `007BD1` | `007BE6` | 1 | K | Unsigned32 [0..200000] kbit/s |  |
| `xdsl2ChConfProfMaxDataRateDs0` | `007BD4` | `007BE9` | 1 | K | Unsigned32 [0..200000] kbit/s |  |
| `xdsl2ChConfProfMaxDataRateUs0` | `007BD5` | `007BEA` | 1 | K | Unsigned32 [0..200000] kbit/s |  |
| `xdsl2ChConfProfMaxDelayDs0` | `007BD8` | `007BED` | 1 | K | Unsigned32 [0..63] ms |  |
| `xdsl2ChConfProfMaxDelayUs0` | `007BD9` | `007BEE` | 1 | K | Unsigned32 [0..63] ms |  |
| `xdsl2ChConfProfMinProtectionDs0` | `007BDA` | `007BEF` | 1 | K | Xdsl2SymbolProtection symbols |  |
| `xdsl2ChConfProfMinProtectionUs0` | `007BDB` | `007BF0` | 1 | K | Xdsl2SymbolProtection symbols |  |
| `xdsl2ChConfProfMinProtection8Ds0` | `007BDC` | `007BF1` | 1 | K | Xdsl2SymbolProtection8 symbols |  |
| `xdsl2ChConfProfMinProtection8Us0` | `007BDD` | `007BF2` | 1 | K | Xdsl2SymbolProtection8 symbols |  |
| `xdslGhsConfOtCarrierSet` | `007CF6` | `007D0B` | 1 | K |  |  |
| `xdslGhsConfRtCarrierSet` | `007CF7` | `007D0C` | 1 | K |  |  |

### A.9. Miscellaneous

| Symbol | Addr 1.60 | Addr 1.61 | Words | Class | Type / Unit | Description |
|---|---|---|---:|:---:|---|---|
| `SystemFlag3` | `000012` | = | 1 | – |  |  |
| `xdslLineDiagTrn` | `006C69` | = | 1 | – |  |  |
| `xdslLineDiagTrnD` | `006C6A` | = | 1 | – |  |  |
| `xdslLineDiagTrnDD` | `006C6B` | = | 1 | – |  |  |
| `xdslIopStatus0` | `006EA1` | `006EB9` | 1 | – |  |  |
| `xdslIopStatus1` | `006EA2` | `006EBA` | 1 | – |  |  |
| `xdslIopStatus2` | `006EA3` | `006EBB` | 1 | – |  |  |
| `xdslIopStatus3` | `006EA4` | `006EBC` | 1 | – |  |  |
| `xdslSecondCnt` | `006EA5` | `006EBD` | 1 | C |  |  |

## Appendix B. Example Exchanges

EBM messages only (frame offset 14 onward, padding omitted). Example MAC addresses:
host `02:00:00:00:00:01`, device `02:00:00:00:00:02`.

**CONNECT:**

```
H→D  0008 31 00000001 ff  ffffffff 00000000     stage 1
D→H  000e b1 00000001 e0  00000002 95743926     magic OK
H→D  0004 31 00000001 ff  6e6f6961 00000000     stage 2 ("noia")
D→H  000c b1 00000001 e1  000000000000         6 payload bytes
```

Stage 1 request: Length `0008` covers the 8 payload bytes. Stage 2 request: Length `0004`
covers `"noia"`; the following zero bytes are padding. Responses: Length = 6 + payload
(`000e` = 6 + 8, `000c` = 6 + 6).

**READ of the identification block:**

```
H→D  0006 01 00000001 ff  01 006c36 0003        READ X:006C36
D→H  0009 81 00000001 00  474154                "GAT"
H→D  0006 01 00000002 ff  01 006c31 0003        READ X:006C31
D→H  0009 81 00000002 00  750202                xdslFirmwareVer
H→D  0006 01 00000003 ff  01 006c32 0003        READ X:006C32
D→H  0009 81 00000003 00  090718                xdslFirmwareDate = 2018-09-07
H→D  0006 01 00000004 ff  01 006c33 0003        READ X:006C33
D→H  0009 81 00000004 00  173044                xdslFirmwareTime = 17:30:44
```

**Layout check** (8.2, branch 1.60 address of `xdsl2LineBand9`):

```
H→D  0006 01 00000005 ff  01 006ffb 0003        READ X:006FFB
D→H  0009 81 00000005 00  000001                upstream(1): branch 1.60 layout
```

**Complete request frame** (READ X:006C35, 64 bytes):

```
02 00 00 00 00 02 02 00 00 00 00 01 61 20 00 06
01 00 00 00 06 ff 01 00 6c 35 00 03 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

## Appendix C. Unverified Items and Open Issues

**Unverified** (consistent with all available information, not observed on a device):

1. Contents of spaces Y and P (7.1).
2. Channel indices 1 and 3 as second bearer channel (9.1).
3. `RaMode`, `XdslMode` value lists, taken from RFC 5650 (9.5); `SnrMode` value `2`.
4. Units and scaling of registers in Appendix A that are not stated as observed in
   Section 9.
5. The layout check and the showtime plausibility check (8.2) on firmware other than
   branch 1.60, in particular the 1.61 addresses on a branch 1.61 device.
6. Composition of `…Hi`/`…Lo` counter pairs (7.2).
7. Treatment of `FFFFCC` (7.3).
8. Minimum request interval (6.3).
9. Broadcast CONNECT (6.1).
10. DISCONNECT (5.4) has not been observed on the wire; its effect on the device is
    unknown.
11. Atomicity of multi-command READ requests (5.5).
12. `xdslMetanoiaShowtimeSeconds` outside showtime and after overflow (9.3.6).
13. Retrain reason value `0` (9.4).
14. Counting of CRC errors in `xdslMetanoiaRtCurrCodingViolations0`/`1` (9.1, 11).
15. `xdsl2ChStatusActDelay`/`ActInp` when retransmission (G.INP) is in use (9.1).
16. The base-62 format of the inventory version number (9.2.4); only the ASCII format has
    been observed.

**Open issues:**

1. A legacy-format read (5.6) of address `6C36` has been observed before CONNECT. The
   device answered with the data bytes `455631` (ASCII `"EV1"`), not with the
   signature `"GAT"` that a READ of `X:006C36` returns. The meaning of the answer is
   unknown; it may be a protocol version indication.
   ```
   H→D  0007 01 6c36 000000 4f22                   legacy read, seq 1, addr 6C36, CRC
   D→H  0006 01 6c36 455631                        "EV1"
   ```
   The CRC polynomial is not specified here.
2. The use of EtherType `0x6122` in connection with this device is unknown.
3. The CONNECT stage 1 response value `0x00000002` and the stage 1 request parameter at
   offset 12 are not understood.
4. `ModemStatus` values other than `00000F` and the bits of `ModemErrOvrflow` are unknown.
5. The branch 1.60 layout has been checked for firmware `750202` / 2018-09-07 / 17:30:44
   in all registers named in Section 8.2 and 9 as observed, in and out of showtime;
   registers outside the checked areas may still differ.
6. Meaning of the `xdslMetanoiaOt*` counter values on an RT device (9.1).
7. A single READ command with Count > 3 (5.5). Not needed: several commands per request
   provide the same speed-up.
8. Session lifetime, the device's answer to READ without CONNECT, and the meaning of
   error Status values (6.4).
9. No discovery mechanism for the device MAC address is known (6.1).
10. Reading per-tone diagnostic data (bit allocation, gains, SNR, QLN, Hlog): packing of
    the `xdsl2SCStatusSegment*` buffers and segment selection.
11. Further message types (e.g. for memory dumps or file transfer) may exist; they are
    not covered by this document.
