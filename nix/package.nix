# The Django web app as a self-contained package: app source, built CSS,
# collected static files, the taxonomy JSON tree it seeds from, and wrappers.
#
#   bin/personnel-web     gunicorn serving config.wsgi (extra args pass through)
#   bin/personnel-manage  manage.py
#   share/personnel-web/app          Django project (STATIC_ROOT = app/staticfiles)
#   share/personnel-web/taxonomy-data  taxonomy/, profiles/, services/
{
  lib,
  stdenvNoCC,
  python3,
  tailwindcss,
  makeWrapper,
}:

let
  fs = lib.fileset;
  root = ../.;

  python = python3.withPackages (ps: [
    ps.django
    ps.django-htmx
    ps.django-axes
    ps.gunicorn
    ps.whitenoise
    ps.argon2-cffi
    ps.openpyxl
  ]);
in
stdenvNoCC.mkDerivation {
  pname = "personnel-web";
  version = "0.1.0";

  src = fs.toSource {
    inherit root;
    fileset = fs.unions [
      (fs.difference ../web (
        fs.unions [
          (fs.maybeMissing ../web/node_modules)
          (fs.maybeMissing ../web/staticfiles)
          (fs.maybeMissing ../web/static/dist/output.css)
          (fs.fileFilter (f: f.hasExt "sqlite3" || f.hasExt "sqlite3-wal" || f.hasExt "sqlite3-shm") ../web)
        ]
      ))
      ../taxonomy
      ../profiles
      ../services
    ];
  };

  nativeBuildInputs = [
    tailwindcss
    makeWrapper
  ];

  # Throwaway values so settings.py imports; collectstatic touches neither
  # the databases nor anything signed.
  env = {
    DJANGO_SETTINGS_MODULE = "config.settings";
    DJANGO_SECRET_KEY = "build-only-not-a-secret-build-only-not-a-secret-xx";
  };

  buildPhase = ''
    runHook preBuild
    cd web
    tailwindcss -i static/src/input.css -o static/dist/output.css --minify
    cp static/src/background.png static/dist/background.png
    PERSONNEL_DATA_DIR=$TMPDIR ${python}/bin/python manage.py collectstatic --noinput -v 0
    cd ..
    runHook postBuild
  '';

  doInstallCheck = true;

  installPhase = ''
    runHook preInstall
    share=$out/share/personnel-web
    mkdir -p $share/taxonomy-data $out/bin
    cp -r web $share/app
    rm -rf $share/app/node_modules $share/app/static/src
    find $share/app -name tests -type d -prune -exec rm -rf {} +
    cp -r taxonomy profiles services $share/taxonomy-data/

    makeWrapper ${python}/bin/gunicorn $out/bin/personnel-web \
      --chdir $share/app \
      --set-default DJANGO_SETTINGS_MODULE config.settings \
      --set-default PERSONNEL_TAXONOMY_DIR $share/taxonomy-data \
      --add-flags config.wsgi:application

    makeWrapper ${python}/bin/python $out/bin/personnel-manage \
      --chdir $share/app \
      --set-default DJANGO_SETTINGS_MODULE config.settings \
      --set-default PERSONNEL_TAXONOMY_DIR $share/taxonomy-data \
      --add-flags $share/app/manage.py
    runHook postInstall
  '';

  # Production settings must import and pass Django's system checks.
  installCheckPhase = ''
    runHook preInstallCheck
    PERSONNEL_DATA_DIR=$TMPDIR $out/bin/personnel-manage check --deploy --fail-level ERROR
    test -f $out/share/personnel-web/app/staticfiles/staticfiles.json
    test -f $out/share/personnel-web/taxonomy-data/taxonomy/_meta.json
    runHook postInstallCheck
  '';

  passthru = { inherit python; };

  meta = {
    description = "Web interface for the Security Lab Personnel Skill Database";
    mainProgram = "personnel-web";
    platforms = lib.platforms.linux;
  };
}
