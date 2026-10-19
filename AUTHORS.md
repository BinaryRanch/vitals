# Authorship

Vitals was built by two parties, and the split is not decorative.

**Christian Sass** — product direction and requirements. The question that
started it ("why are all my CPUs pegged, and why is this process manager
useless at telling me?") is his. So is the framing that gave the tool its shape:
the browser is the top layer of the operating system, so a process monitor that
stops at the browser boundary is measuring the wrong thing. He supplied the field
evidence, including the ten leaked headless browser instances that made the
failure mode concrete, and he made every product call about what belongs on the
screen and what does not.

**CLU** (Codified Likeness Utility, Binary Ranch) — architecture and
implementation. Identity resolution, the CDP client and the tab-to-process join,
the sampler, the UI, the tests, the demo mode, and this documentation.

Both parties reviewed the result together against live machine data. Where the
code is wrong, it is CLU's error. Where the tool is pointed at the wrong
question, it is Christian's.

## Attribution

If you cite or fork this work, credit both: "Vitals, Christian Sass and CLU
(Binary Ranch)". Commits carry a `Co-developed-with` trailer for the same
reason.

Contact: csass@binaryranch.com
