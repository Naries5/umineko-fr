using System.IO.Compression;
using UminekoFR;

string root = Path.GetFullPath(args[0]);
var manifest = await UpdaterCore.GetRemoteManifestAsync("http://127.0.0.1:8765/candidate-manifest.json");
if (manifest.Version != "0.1.22" || manifest.SchemaVersion != 3 ||
    manifest.Files?.Count != 4047 || manifest.Packages?.Count != 21 ||
    manifest.DeletePaths is { Count: > 0 })
    throw new Exception("Candidate manifest format mismatch");
if (manifest.DownloadUrl != "https://github.com/Naries5/umineko-fr/releases/download/v0.1.22/patch-fr-0.1.22.zip" ||
    manifest.Sha256 != UpdaterCore.ComputeFileSha256(Path.Combine(root,"patch-fr-0.1.22.zip")))
    throw new Exception("Legacy full-patch fields mismatch");
manifest.Packages.Single(p => p.Id == "questions-022").DownloadUrl =
    "http://127.0.0.1:8765/UminekoFR-Questions-0.1.22.zip";
// Test the exact core against an isolated copy of the previous patch.
// No game executable is present in this fixture, so bypass only 07th-Mod detection.
manifest.Requires07thMod = false;
string game = Path.Combine(root,"compat-game");
ZipFile.ExtractToDirectory(Path.Combine(root,"../old-release/patch-fr-0.1.21.zip"),game);
File.WriteAllText(Path.Combine(game,UpdaterCore.LocalVersionFile),"0.1.21");
var logs = new List<string>();
bool changed = await UpdaterCore.UpdateToManifestAsync(game,manifest,logs.Add,verifyAll:true);
if (!changed || logs.Count(l=>l.StartsWith("Téléchargement :")) != 1 ||
    !logs.Contains("Téléchargement : questions-022..."))
    throw new Exception("Expected exactly one incremental package download");
foreach (var f in manifest.Files)
{
    string p = Path.Combine(game,f.Path);
    if (new FileInfo(p).Length != f.Size ||
        UpdaterCore.ComputeFileSha256(p) != f.Sha256)
        throw new Exception("Installed file mismatch: "+f.Path);
}
if (await UpdaterCore.UpdateToManifestAsync(game,manifest))
    throw new Exception("Second run should be a no-op");
Console.WriteLine("PASS: unchanged production updater core installed only questions-022 from v0.1.21; all 4047 file hashes/sizes match; second run no-op; legacy full-patch URL/hash valid.");
