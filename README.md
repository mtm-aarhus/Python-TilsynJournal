# TilsynJournal Process

OpenOrchestrator process for journalizing inspections from the AAK Tilsyn app.

## What it does

Processes queue elements from the **TilsynJournal** queue, branching on item type:

### Henstilling → PEZ comment
- Looks up the `PEZUUID` from Cosmos DB
- Logs into PEZ and posts an internal comment with inspection details
- Comment includes: initials, date/time, kvadratmeter, slutdato/sidst set, fakturastatus, and comment
- Label is "Sidst set" when fakturastatus is `Ny`, otherwise "Slutdato"
- Comment is truncated to 3500 chars (PEZ limit ~4000) — only the free-text comment is cut

### Permission → PDF upload to Vejman
- Only processes actual inspections (skips hide/remove actions)
- Generates a PDF report with a formatted table: tilsynsførende, dato, tidspunkt, kategori, and supplerende kommentar
- Uploads the PDF to Vejman using the same file endpoint as TilsynBilleder
- Filename format: `INITIALS_DDMMYY_HHMM_Kategori_Kommentar (...).pdf`
- Total filename is capped at 215 characters

## Credentials (OpenOrchestrator)

| Name | Username | Password |
|------|----------|----------|
| `AAKTilsynDB` | Cosmos URL | Cosmos key |
| `PEZUI` | PEZ username | PEZ password |
| `VejmanToken` | — | Vejman API token |

## Dependencies

- `fpdf2`
- `azure-cosmos`
- `requests`

## Queue element examples

**Henstilling:**
```json
{
    "id": "123456_1",
    "type": "henstilling",
    "inspector_email": "inspector@aarhus.dk",
    "comment": "",
    "inspected_at": "2026-04-14T14:20:24",
    "updates": {
        "kvadratmeter": 22,
        "end_date": "2026-04-14",
        "fakturaStatus": "Ny"
    }
}
```

**Permission:**
```json
{
    "id": "12345678",
    "type": "permission",
    "inspector_email": "inspector@aarhus.dk",
    "comment": "Test",
    "selection": "Alt okay",
    "inspected_at": "2026-04-14T14:08:08"
}
```


# Robot-Framework V4

This repo is meant to be used as a template for robots made for [OpenOrchestrator](https://github.com/itk-dev-rpa/OpenOrchestrator) v2.

## Quick start

1. To use this template simply use this repo as a template (see [Creating a repository from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)).
__Don't__ include all branches.

2. Go to `robot_framework/__main__.py` and choose between the linear framework or queue based framework.

3. Implement all functions in the files:
    * `robot_framework/initialize.py`
    * `robot_framework/reset.py`
    * `robot_framework/process.py`

4. Change `config.py` to your needs.

5. Fill out the dependencies in the `pyproject.toml` file with all packages needed by the robot.

6. Feel free to add more files as needed. Remember that any additional python files must
be located in the folder `robot_framework` or a subfolder of it.

When the robot is run from OpenOrchestrator the `main.py` file is run which results
in the following:

1. The working directory is changed to where `main.py` is located.
2. A virtual environment is automatically setup with the required packages.
3. The framework is called passing on all arguments needed by [OpenOrchestrator](https://github.com/itk-dev-rpa/OpenOrchestrator).

## Requirements

Minimum python version 3.11

## Flow

This framework contains two different flows: A linear and a queue based.
You should only ever use one at a time. You choose which one by going into `robot_framework/__main__.py`
and uncommenting the framework you want. They are both disabled by default and an error will be
raised to remind you if you don't choose.

### Linear Flow

The linear framework is used when a robot is just going from A to Z without fetching jobs from an
OpenOrchestrator queue.
The flow of the linear framework is sketched up in the following illustration:

![Linear Flow diagram](Robot-Framework.svg)

### Queue Flow

The queue framework is used when the robot is doing multiple bite-sized tasks defined in an
OpenOrchestrator queue.
The flow of the queue framework is sketched up in the following illustration:

![Queue Flow diagram](Robot-Queue-Framework.svg)

## Linting and Github Actions

This template is also setup with flake8 and pylint linting in Github Actions.
This workflow will trigger whenever you push your code to Github.
The workflow is defined under `.github/workflows/Linting.yml`.
