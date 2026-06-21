"""TDD for the repro-enforcer trust instrument (Exp 2, Phase 3).

Two calling runs are reproducible if (default mode) they yield identical genotypes within the confident
region, ignoring header and record-order noise and GT allele order; the optional byte mode requires
byte-identical files. Reproducibility also requires the two runs to share identical pins.
"""
from __future__ import annotations

import repro_enforcer as RE


_VCF_A = """##fileformat=VCFv4.2
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE
chr20\t100\t.\tA\tT\t50\tPASS\t.\tGT\t0/1
chr20\t200\t.\tG\tC\t60\tPASS\t.\tGT\t1/1
"""

# same genotypes, different record order, different QUAL, phased/swapped GT, extra header line
_VCF_B = """##fileformat=VCFv4.2
##note=reordered
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE
chr20\t200\t.\tG\tC\t99\tPASS\t.\tGT\t1|1
chr20\t100\t.\tA\tT\t10\tPASS\t.\tGT\t1/0
"""

_VCF_C = """##fileformat=VCFv4.2
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE
chr20\t100\t.\tA\tT\t50\tPASS\t.\tGT\t0/1
chr20\t300\t.\tT\tA\t40\tPASS\t.\tGT\t0/1
"""


def test_parse_vcf_genotypes():
    recs = RE.parse_vcf_genotypes(_VCF_A)
    assert ("chr20", 100, "A", "T", "0/1") in recs
    assert len(recs) == 2


def test_gt_normalisation_is_order_and_phase_insensitive():
    assert RE.normalise_gt("1/0") == "0/1"
    assert RE.normalise_gt("0|1") == "0/1"
    assert RE.normalise_gt("1|1") == "1/1"


def test_genotype_identical_ignores_order_qual_and_phase():
    v = RE.genotype_identical(_VCF_A, _VCF_B)
    assert v["identical"] is True
    assert v["only_a"] == 0 and v["only_b"] == 0


def test_genotype_difference_is_reported():
    v = RE.genotype_identical(_VCF_A, _VCF_C)
    assert v["identical"] is False
    # A has 200; C has 300; 100 shared
    assert v["only_a"] == 1 and v["only_b"] == 1


def test_byte_identical(tmp_path):
    a = tmp_path / "a.vcf"; a.write_text(_VCF_A)
    b = tmp_path / "b.vcf"; b.write_text(_VCF_A)
    c = tmp_path / "c.vcf"; c.write_text(_VCF_B)
    assert RE.byte_identical(a, b) is True
    assert RE.byte_identical(a, c) is False


def test_same_pins_requires_matching_provenance():
    pa = {"sarek_version": "3.8.1", "reference_sha256": "x", "container_digests": {"s": "d"}}
    pb = dict(pa)
    pc = dict(pa, sarek_version="3.9.0")
    assert RE.same_pins(pa, pb) is True
    assert RE.same_pins(pa, pc) is False


def test_enforce_genotype_mode_requires_pins_and_genotypes():
    pins = {"sarek_version": "3.8.1", "reference_sha256": "x", "container_digests": {"s": "d"}}
    v = RE.enforce({"vcf": _VCF_A, "provenance": pins}, {"vcf": _VCF_B, "provenance": pins}, mode="genotype")
    assert v["reproducible"] is True
    # divergent pins fail even if genotypes match
    v2 = RE.enforce({"vcf": _VCF_A, "provenance": pins},
                    {"vcf": _VCF_B, "provenance": dict(pins, sarek_version="9")}, mode="genotype")
    assert v2["reproducible"] is False
    assert v2["reason"] == "pin_mismatch"
