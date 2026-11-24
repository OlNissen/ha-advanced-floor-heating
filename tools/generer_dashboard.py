#!/usr/bin/env python3
"""Genererer et Lovelace-dashboard (YAML) til Advanced Floor Heating.

Brug (kun Python 3, ingen ekstra pakker):

    python tools/generer_dashboard.py stue kontor bad > dashboard/varmestyring.yaml
    python tools/generer_dashboard.py "stue=Stue" "sovevaerelse=Soveværelse"

Hvert argument er enten bare rummets entity-id-navn, eller `entity-id=Pænt navn`.
"Entity-id-navn" er det, der står efter `climate.`, fx `stue` i `climate.stue`.
Du finder dem i Indstillinger -> Enheder & tjenester -> Entiteter (søg på "Floor").

For hvert rum bruges disse entities (de oprettes automatisk af integrationen):
    climate.<id>                 termostat
    number.<id>_gulv_setpunkt      ønsket gulvtemperatur
    sensor.<id>_pid_signal       varmeeffekt i %
    sensor.<id>_reguleringsstatus
"""
import sys

HEADER = """\
# Advanced Floor Heating - dashboard til alle rum
# Genereret af tools/generer_dashboard.py - ret rum ved at generere filen igen,
# eller kopiér/slet blokke herunder (ét rum = ét "vertical-stack").
# Kræver Home Assistant 2024.8 eller nyere. Ingen ekstra kort fra HACS nødvendige.
title: Varmestyring
views:
  - title: Varme
    path: varme
    icon: mdi:radiator
    cards:
"""


def parse(arg):
    slug, _, name = arg.partition("=")
    slug = slug.strip().removeprefix("climate.")
    name = name.strip() or slug.replace("_", " ").title()
    return slug, name


def room_card(slug, name):
    c = f"climate.{slug}"
    return f"""\
      # ---------- {name} ----------
      - type: vertical-stack
        cards:
          - type: thermostat
            entity: {c}
            name: {name}
            features:
              - type: climate-hvac-modes
                hvac_modes: [heat, "off"]
              - type: climate-preset-modes
                style: dropdown
                preset_modes:
                  - Kun Rum
                  - Kun Gulv
                  - Rum & Gulv (1 Opfyldt)
                  - Rum & Gulv (Begge Opfyldt)
          - type: entities
            show_header_toggle: false
            entities:
              - type: attribute
                entity: {c}
                attribute: room_temperature
                name: Rumtemperatur
                suffix: °C
              - type: attribute
                entity: {c}
                attribute: room_target_temperature
                name: Ønsket rumtemperatur
                suffix: °C
              - type: attribute
                entity: {c}
                attribute: floor_temperature
                name: Gulvtemperatur
                suffix: °C
              - entity: number.{slug}_gulv_setpunkt
                name: Ønsket gulvtemperatur
              - entity: sensor.{slug}_pid_signal
                name: Varmeeffekt
              - entity: sensor.{slug}_reguleringsstatus
                name: Status
              - type: attribute
                entity: {c}
                attribute: window_open
                name: Vindue åbent
              - type: attribute
                entity: {c}
                attribute: output_frozen
                name: Udgang frosset (vindue)
"""


def indent(text, n):
    return "".join(" " * n + line if line.strip() else line for line in text.splitlines(True))


def overview_cards(rooms):
    ents = "".join(f"- entity: climate.{slug}\n  name: {name}\n" for slug, name in rooms)
    targets = ", ".join(f"climate.{slug}" for slug, _ in rooms)

    def button(label, icon, service):
        return "".join(l + "\n" for l in [
            "- type: button",
            f"  name: {label}",
            f"  icon: {icon}",
            "  tap_action:",
            "    action: perform-action",
            f"    perform_action: climate.{service}",
            "    target:",
            f"      entity_id: [{targets}]",
        ])

    buttons = button("Alle til", "mdi:radiator", "turn_on") + button("Alle fra", "mdi:radiator-off", "turn_off")
    head = "".join(l + "\n" for l in [
        "      # ---------- Overblik ----------",
        "      - type: vertical-stack",
        "        cards:",
        "          - type: entities",
        "            title: Alle rum",
        "            show_header_toggle: false",
        "            entities:",
    ])
    mid = "".join(l + "\n" for l in [
        "          - type: horizontal-stack",
        "            cards:",
    ])
    return head + indent(ents, 14) + mid + indent(buttons, 14)



def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 1
    rooms = [parse(a) for a in argv]
    out = [HEADER, overview_cards(rooms)]
    out += [room_card(slug, name) for slug, name in rooms]
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write("".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
