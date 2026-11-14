using System.IO.Compression;
using UminekoFR;

if (new Version("1.0.0") <= new Version("0.1.23")) throw new Exception("Major version comparison failed");
string root = Path.GetFullPath(args[0]);
bool published = args.Length > 1 && args[1] == "published";
var manifest = await UpdaterCore.GetRemoteManifestAsync(published
    ? "https://raw.githubusercontent.com/Naries5/umineko-fr/main/update/manifest.json"
    : "http://127.0.0.1:8765/candidate-manifest.json");
if (manifest.Version != "1.0.0" || manifest.SchemaVersion != 3 ||
    manifest.Files?.Count != 4047 || manifest.Packages?.Count != 23 ||
    manifest.DeletePaths is { Count: > 0 })
    throw new Exception("Candidate manifest format mismatch");
if (manifest.DownloadUrl != "https://github.com/Naries5/umineko-fr/releases/download/v1.0.0/patch-fr-1.0.0.zip" ||
    manifest.Sha256 != UpdaterCore.ComputeFileSha256(Path.Combine(root,"patch-fr-1.0.0.zip")))
    throw new Exception("Legacy full-patch fields mismatch");
if (!published) manifest.Packages.Single(p => p.Id == "questions-100").DownloadUrl =
    "http://127.0.0.1:8765/UminekoFR-Questions-1.0.0.zip";
// Test the exact core against an isolated copy of the previous patch.
// No game executable is present in this fixture, so bypass only 07th-Mod detection.
manifest.Requires07thMod = false;
string game = Path.Combine(root,published ? "published-game" : "compat-game");
ZipFile.ExtractToDirectory(Path.Combine(root,"../old-release/patch-fr-0.1.23.zip"),game);
File.WriteAllText(Path.Combine(game,UpdaterCore.LocalVersionFile),"0.1.23");
var logs = new List<string>();
bool changed = await UpdaterCore.UpdateToManifestAsync(game,manifest,logs.Add,verifyAll:true);
if (!changed || logs.Count(l=>l.StartsWith("Téléchargement :")) != 1 ||
    !logs.Contains("Téléchargement : questions-100..."))
    throw new Exception("Expected exactly one incremental package download");
foreach (var f in manifest.Files)
{
    string p = Path.Combine(game,f.Path);
    if (new FileInfo(p).Length != f.Size ||
        UpdaterCore.ComputeFileSha256(p) != f.Sha256)
        throw new Exception("Installed file mismatch: "+f.Path);
}
var snapshot = Directory.GetFiles(game,"*",SearchOption.AllDirectories).ToDictionary(p=>p,p=>(new FileInfo(p).Length,File.GetLastWriteTimeUtc(p),UpdaterCore.ComputeFileSha256(p)));
if (await UpdaterCore.UpdateToManifestAsync(game,manifest))
    throw new Exception("Second run should be a no-op");
if (!snapshot.Keys.Order().SequenceEqual(Directory.GetFiles(game,"*",SearchOption.AllDirectories).Order()) ||
    snapshot.Any(kv => kv.Value != (new FileInfo(kv.Key).Length,File.GetLastWriteTimeUtc(kv.Key),UpdaterCore.ComputeFileSha256(kv.Key))))
    throw new Exception("Second run changed files or timestamps");
Console.WriteLine("PASS: unchanged production updater core installed only questions-100 from v0.1.23; all 4047 file hashes/sizes match; second run no-op; legacy full-patch URL/hash valid.");
