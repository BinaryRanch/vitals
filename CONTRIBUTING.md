# Contributing to Vitals

Thanks for looking. This is a small tool and the bar is simple: it must stay
readable, it must stay dependency-free, and it must not lie about what it
measures.

## License of contributions

Vitals is MIT licensed. Contributions are accepted under MIT, inbound equal to
outbound. There is no CLA to sign and no paperwork.

You keep the copyright on what you write. You are licensing it to everyone under
MIT, which is the same thing everyone else already gets.

## Sign your commits

Every commit needs a `Signed-off-by` line. That is the Developer Certificate of
Origin: a one-line statement that you wrote the change, or have the right to
submit it, and that you are contributing it under this project's license.

Git adds it for you:

```bash
git commit -s -m "your message"
```

Which produces:

```
Signed-off-by: Your Name <you@example.com>
```

A pull request whose commits lack the sign-off will fail the check. That is not
distrust, it is provenance: it is what protects the project if a contribution
later turns out to belong to someone's employer.

**If you contribute as part of your job**, confirm with your employer first. The
sign-off asserts you have that permission.

## What gets merged

- Fixes with a reproduction. A bug report that names the machine and the
  measurement is worth more than a patch that guesses.
- New identity resolvers for the sampler, especially for desktops that are not
  this one. The resolver model is documented in the README.
- Documentation corrections, including corrections to this file.

## What does not get merged

- Dependencies. The whole point is that this runs on a bare Python with nothing
  installed. If a change needs a package, it needs a very good argument.
- Client code, customer data, credentials, hostnames, or anything taken from a
  machine that is not yours. Scrub before you paste.
- Claims in the UI that the sampler cannot back with a number.
- Anything that requires root.

## Reporting a problem

Open an issue. Include the workload row or the verdict line you saw, and the
output of `python3 server.py --demo` if the problem is in the interface.

For anything that looks like a security problem, mail csass@binaryranch.com
rather than opening a public issue.

## Authorship

Contributors are credited in `AUTHORS.md`. Add yourself when your first change
lands.
