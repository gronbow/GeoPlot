fn main() {
    println!("cargo:rerun-if-env-changed=GEOSKILLS_DESKTOP_SOURCE_PYTHON");
    if let Ok(python) = std::env::var("GEOSKILLS_DESKTOP_SOURCE_PYTHON") {
        println!("cargo:rustc-env=GEOSKILLS_DESKTOP_SOURCE_PYTHON={python}");
    }
    tauri_build::build()
}
