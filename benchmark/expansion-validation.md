# Five-Repository Benchmark Expansion Validation

Recorded on 2026-09-10 without model calls.

The real-project manifest now defines eight single-fault cases across five pinned, licensed PyTorch image-classification repositories. The two added repositories are:

| Repository | License | Pinned commit | Added fault |
|---|---|---|---|
| `kuangliu/pytorch-cifar` | MIT | `49b7aa97b0c12fe0d4054e670403a16b6b834ddd` | evaluation loader uses the training split |
| `soapisnotfat/pytorch-cifar10` | Apache-2.0 | `1e49822683bf0800a3f4f7f0df778cb5ba6a87fe` | accuracy divides by batches instead of samples |

Both additions passed the deterministic expansion gate:

- exact commit and license recorded;
- allowed source path exists;
- original source passes the semantic probe;
- injection patch applies cleanly;
- injected source fails with the expected diagnosis category;
- data and metric repairs are declared as approval-required.

After repository acquisition and commit verification, each injection/probe validation used four deterministic tool calls. This proves that the cases are well-formed; it is not an LLM repair result. The published model-driven baseline remains the six evaluated cases across the original three repositories until all eight cases are rerun with a newly configured model credential. Its exact inputs remain frozen in [`real-projects-2026-09-03.yaml`](real-projects-2026-09-03.yaml).
