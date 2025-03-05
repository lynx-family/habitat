# habitat

Habitat is a lightweight command line tool to manage source and binary dependencies in monorepo, plus dependency
integration in CI environment.

It is also easy to use for developers. No need to execute many commands manually, just run `./hab sync .` to set up
local development environment.

## Installation

We provide both a binary (hab.pex) and a wrapper script. You can find them in the releases and choose to download one of them as your need.

The simplest way is to download the wrapper using following instruction:
```shell
curl -L -O https://github.com/lynx-family/habitat/releases/latest/download/hab | chmod +x hab
```

## Usage

1. Generate habitat configuration file in the repo.

   ```bash
   ./hab config <repo remote uri>
   ```

   A .habitat file will be generated. it should look like this.
   ```python
   solutions = [
       {
           'name': '.',
           'deps_file': 'DEPS',  # dependency list
           'url': 'git@github.com:namespace/repo.git'  # main repo's remote url
       }
   ]
   ```

2. Add a dependency in DEPS file.
   ```python
   deps = {
       'lib/example': {
           'type': 'git',
           'url': 'git@github.com:namespace/lib.git',
           'branch': 'dev'
       }
   }
   ```

3. Track habitat wrapper script and configuration files.

   ```bash
   git add hab .habitat DEPS && git commit -m "Add habitat to manage dependencies."
   ```

4. Integrate the `dev` branch of dependency to path `lib/example`.

   ```bash
   ./hab sync .
   ```

## Development

Recommend to develop with Python higher than 3.9.

```bash
python3 -m venv _venv
source _venv/bin/activate
make install_dev
```

Running tests after making any changes is strongly recommended.

```bash
make check
```

## Contributing

See [the contributing file](./CONTRIBUTING.md)!

## License

[Apache License 2.0](./LICENSE)
