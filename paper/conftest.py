# paper/tests holds copies of repository tests for reference; the originals in <repo>/tests are the ones
# pytest should run, so the copies are not collected (identical module names would clash).
collect_ignore_glob = ["tests/*", "experiments/*"]
