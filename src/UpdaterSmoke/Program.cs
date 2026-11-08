using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using UminekoFR;

internal static class SmokeTest
{
    private static async Task Main()
    {
        const string manifestUrl = "https://raw.githubusercontent.com/Naries5/umineko-fr/main/update/manifest.json";
        var manifest = await UpdaterCore.GetRemoteManifestAsync(manifestUrl);
        if (manifest.Version != "0.1.18" || manifest.SchemaVersion != 3)
            throw new Exception("Manifest version/schema mismatch.");
        if (manifest.Packages is null || manifest.Packages.Count < 10 ||
            manifest.Files is null || manifest.Files.Count < 4000)
            throw new Exception("Manifest has no V3 files/packages.");
        if (!manifest.Files.Any(f => f.Path == "0.u"))
            throw new Exception("Core file missing from manifest.");

        // Check that update-to-current can return successfully without writing
        // patch assets or downloading game files (safe local smoke test).
        string folder = Path.Combine(Path.GetTempPath(), "umineko_smoke_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(folder);
        try
        {
            File.WriteAllText(Path.Combine(folder, UpdaterCore.LocalVersionFile), manifest.Version);
            manifest.Requires07thMod = false;
            bool changed = await UpdaterCore.UpdateToManifestAsync(folder, manifest);
            if (changed) throw new Exception("Same-version update should be a no-op.");
        }
        finally { Directory.Delete(folder, recursive: true); }
        Console.WriteLine("PASS: updater core compiles, parses V3 manifest, and same-version path is safe.");
    }
}
