"""
NemoFold Jury Design Set Generator - Visual Asset Suite
Builds deterministic SVGs and renders host-rendered raster PNGs for:
- Concept A: trust-voyage (1600x900, 1280x720, 1200x630)
- Concept B: evidence-ledger (1600x900, 1280x720, 1200x630)
- Concept C: bounded-reasoning (1600x900, 1280x720, 1200x630)
"""

# The generator intentionally keeps SVG markup as readable inline templates.
# ruff: noqa: E501

import json
import os
import subprocess

from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==============================================================================
# CONCEPT A — trust-voyage
# ==============================================================================
def get_concept_a_svg(width, height, variant_name):
    scale = width / 1600.0
    
    if variant_name == "banner":
        # 1600 x 900
        pad_x = 90
        pad_y = 90
        eb_w = 430
        prod_y = pad_y + 115
        hl_y1 = pad_y + 205
        hl_y2 = pad_y + 280
        sup_y = pad_y + 360
        chip_y = pad_y + 440
        chip_w = 510
        badge_x = 960
        badge_y = 150
        badge_w = 550
        badge_h = 580
        eb_fs = 14
        prod_fs = 46
        hl_fs = 64
        sup_fs = 24
        chip_fs = 18
        card_title_fs = 16
        card_item_fs = 13.5
        card_num_fs = 14
        row_title_fs = 16
        badge_summary_fs = 13.5
    elif variant_name == "thumbnail":
        # 1280 x 720
        pad_x = 72
        pad_y = 65
        eb_w = 360
        prod_y = pad_y + 90
        hl_y1 = pad_y + 165
        hl_y2 = pad_y + 225
        sup_y = pad_y + 290
        chip_y = pad_y + 355
        chip_w = 420
        badge_x = 770
        badge_y = 115
        badge_w = 440
        badge_h = 470
        eb_fs = 12
        prod_fs = 38
        hl_fs = 50
        sup_fs = 19
        chip_fs = 14
        card_title_fs = 13
        card_item_fs = 11.5
        card_num_fs = 12
        row_title_fs = 13.5
        badge_summary_fs = 11.5
    else: # social 1200 x 630
        pad_x = 64
        pad_y = 55
        eb_w = 345
        prod_y = pad_y + 80
        hl_y1 = pad_y + 148
        hl_y2 = pad_y + 204
        sup_y = pad_y + 262
        chip_y = pad_y + 322
        chip_w = 400
        badge_x = 720
        badge_y = 90
        badge_w = 420
        badge_h = 445
        eb_fs = 11.5
        prod_fs = 36
        hl_fs = 46
        sup_fs = 18
        chip_fs = 13.5
        card_title_fs = 12.5
        card_item_fs = 11
        card_num_fs = 11.5
        row_title_fs = 13
        badge_summary_fs = 11

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="NemoFold - Trust Voyage">
  <defs>
    <!-- Dark Scrim & Atmospheric Vignette -->
    <linearGradient id="scrimA_{variant_name}" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#031218" stop-opacity="0.98"/>
      <stop offset="35%" stop-color="#041820" stop-opacity="0.94"/>
      <stop offset="58%" stop-color="#072C37" stop-opacity="0.75"/>
      <stop offset="82%" stop-color="#073B49" stop-opacity="0.30"/>
      <stop offset="100%" stop-color="#0B4A59" stop-opacity="0.10"/>
    </linearGradient>
    <radialGradient id="vignetteA_{variant_name}" cx="50%" cy="50%" r="70%">
      <stop offset="45%" stop-color="#000000" stop-opacity="0"/>
      <stop offset="100%" stop-color="#010A0E" stop-opacity="0.70"/>
    </radialGradient>
    <linearGradient id="cardGradA_{variant_name}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#073B49" stop-opacity="0.88"/>
      <stop offset="100%" stop-color="#041E26" stop-opacity="0.94"/>
    </linearGradient>
    <linearGradient id="accentGradA_{variant_name}" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#5AD2D0"/>
      <stop offset="50%" stop-color="#1F9D72"/>
      <stop offset="100%" stop-color="#FF6B4A"/>
    </linearGradient>
    <filter id="glowA_{variant_name}" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="6" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
    <filter id="shadowCardA_{variant_name}" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="16" stdDeviation="22" flood-color="#000000" flood-opacity="0.6"/>
    </filter>
    <style>
      .eb-text-a {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {eb_fs}px; font-weight: 700; fill: #5AD2D0; letter-spacing: 2px; text-transform: uppercase; }}
      .prod-text-a {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {prod_fs}px; font-weight: 800; fill: #F7F1E7; letter-spacing: -0.5px; }}
      .prod-sub-a {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {prod_fs}px; font-weight: 800; fill: #5AD2D0; }}
      .hl-text-a {{ font-family: Georgia, 'Times New Roman', serif; font-size: {hl_fs}px; font-weight: 700; fill: #F7F1E7; letter-spacing: -0.5px; line-height: 1.15; }}
      .sup-text-a {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {sup_fs}px; font-weight: 400; fill: #C8E3E1; letter-spacing: 0.2px; }}
      .chip-text-a {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {chip_fs}px; font-weight: 600; fill: #E6FAF8; letter-spacing: 0.3px; }}
      .card-title-a {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: {card_title_fs}px; font-weight: 700; fill: #F7F1E7; letter-spacing: 1px; }}
      .card-item-a {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: {card_item_fs}px; font-weight: 400; fill: #B3D8D6; }}
    </style>
  </defs>

  <!-- 1. Hero Artwork Background -->
  <image href="sources/trust-voyage-background.png" x="0" y="0" width="{width}" height="{height}" preserveAspectRatio="xMidYMid slice"/>

  <!-- 2. Dark Scrim & Atmospheric Lighting -->
  <rect width="{width}" height="{height}" fill="url(#scrimA_{variant_name})"/>
  <rect width="{width}" height="{height}" fill="url(#vignetteA_{variant_name})"/>

  <!-- Top Accent Ribbon -->
  <rect x="0" y="0" width="{width}" height="{max(3, int(4*scale))}" fill="url(#accentGradA_{variant_name})"/>

  <!-- 3. Left Content Group -->
  <!-- Eyebrow Capsule -->
  <g transform="translate({pad_x}, {pad_y})">
    <rect x="0" y="0" width="{eb_w}" height="{max(26, int(32*scale))}" rx="{max(13, int(16*scale))}" fill="#073B49" fill-opacity="0.85" stroke="#5AD2D0" stroke-width="1.2" stroke-opacity="0.7"/>
    <circle cx="{int(18*scale)}" cy="{max(13, int(16*scale))}" r="{max(3.5, 4.5*scale)}" fill="#5AD2D0"/>
    <text x="{int(34*scale)}" y="{max(17, int(21*scale))}" class="eb-text-a">PRIVATE · PERSISTENT · EVIDENCE-FIRST</text>
  </g>

  <!-- Product Brand Mark & Name -->
  <g transform="translate({pad_x}, {prod_y})">
    <!-- Origami Fold Geometric Icon -->
    <g transform="scale({scale * 0.95})">
      <path d="M0,0 L24,-14 L42,6 L18,20 Z" fill="#FF6B4A"/>
      <path d="M18,20 L42,6 L36,36 L12,48 Z" fill="#5AD2D0"/>
      <path d="M0,0 L18,20 L12,48 L-6,26 Z" fill="#1F9D72"/>
    </g>
    <text x="{int(58*scale)}" y="{int(32*scale)}" class="prod-text-a">Nemo<tspan class="prod-sub-a">Fold</tspan></text>
  </g>

  <!-- Headline -->
  <text x="{pad_x}" y="{hl_y1}" class="hl-text-a">Your files. Your rules.</text>
  <text x="{pad_x}" y="{hl_y2}" class="hl-text-a">Your agent.</text>

  <!-- Supporting Copy -->
  <text x="{pad_x}" y="{sup_y}" class="sup-text-a">Local memory. Bounded reasoning. Verifiable results.</text>

  <!-- Status Chip: Local core ready · Live cloud proof open -->
  <g transform="translate({pad_x}, {chip_y})">
    <rect x="0" y="0" width="{chip_w}" height="{max(36, int(46*scale))}" rx="{max(18, int(23*scale))}" fill="#073B49" fill-opacity="0.92" stroke="#1F9D72" stroke-width="1.8"/>
    <!-- Emerald Status Indicator -->
    <circle cx="{int(24*scale)}" cy="{max(18, int(23*scale))}" r="{max(4.5, 6*scale)}" fill="#1F9D72" filter="url(#glowA_{variant_name})"/>
    <circle cx="{int(24*scale)}" cy="{max(18, int(23*scale))}" r="{max(3.5, 4.5*scale)}" fill="#1F9D72"/>
    <text x="{int(42*scale)}" y="{max(23, int(29.5*scale))}" class="chip-text-a">Local core ready · Live cloud proof open</text>
  </g>

  <!-- 4. Right Hero Feature Matrix Card -->
  <g transform="translate({badge_x}, {badge_y})" filter="url(#shadowCardA_{variant_name})">
    <!-- Main Card Body -->
    <rect width="{badge_w}" height="{badge_h}" rx="{max(12, int(18*scale))}" fill="url(#cardGradA_{variant_name})" stroke="#5AD2D0" stroke-width="1.5" stroke-opacity="0.45"/>
    
    <!-- Inner Header Container -->
    <rect x="0" y="0" width="{badge_w}" height="{max(48, int(64*scale))}" rx="{max(12, int(18*scale))}" fill="#0B4A59" fill-opacity="0.75"/>
    <rect x="0" y="{max(34, int(45*scale))}" width="{badge_w}" height="{max(14, int(19*scale))}" fill="#0B4A59" fill-opacity="0.75"/>
    
    <!-- Header Content -->
    <circle cx="{int(34*scale)}" cy="{max(24, int(32*scale))}" r="{max(7, int(9*scale))}" fill="#1F9D72"/>
    <path d="M{int(30*scale)},{max(24, int(32*scale))} L{int(33*scale)},{max(27, int(35*scale))} L{int(39*scale)},{max(21, int(29*scale))}" fill="none" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round"/>
    <text x="{int(54*scale)}" y="{max(29, int(38*scale))}" class="card-title-a">LOCAL-FIRST TRUST MATRIX</text>
    
    <!-- Row 1: Approved Boundary -->
    <g transform="translate({int(22*scale)}, {int(badge_h * 0.15)})">
      <rect width="{badge_w - int(44*scale)}" height="{int(badge_h * 0.22)}" rx="{max(8, int(12*scale))}" fill="#041E26" fill-opacity="0.75" stroke="#073B49" stroke-width="1.2"/>
      <circle cx="{int(26*scale)}" cy="{int(badge_h * 0.11)}" r="{max(9, int(13*scale))}" fill="#073B49"/>
      <text x="{int(26*scale)}" y="{int(badge_h * 0.11) + int(5*scale)}" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="{card_num_fs}px" font-weight="700" fill="#5AD2D0">1</text>
      <text x="{int(52*scale)}" y="{int(badge_h * 0.085)}" font-family="'Segoe UI', sans-serif" font-size="{row_title_fs}px" font-weight="700" fill="#F7F1E7">Approved Folders Boundary</text>
      <text x="{int(52*scale)}" y="{int(badge_h * 0.155)}" class="card-item-a">Explicit local paths only · Unapproved transfer fails closed</text>
    </g>

    <!-- Row 2: Memory & Ledgers -->
    <g transform="translate({int(22*scale)}, {int(badge_h * 0.40)})">
      <rect width="{badge_w - int(44*scale)}" height="{int(badge_h * 0.22)}" rx="{max(8, int(12*scale))}" fill="#041E26" fill-opacity="0.75" stroke="#073B49" stroke-width="1.2"/>
      <circle cx="{int(26*scale)}" cy="{int(badge_h * 0.11)}" r="{max(9, int(13*scale))}" fill="#073B49"/>
      <text x="{int(26*scale)}" y="{int(badge_h * 0.11) + int(5*scale)}" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="{card_num_fs}px" font-weight="700" fill="#5AD2D0">2</text>
      <text x="{int(52*scale)}" y="{int(badge_h * 0.085)}" font-family="'Segoe UI', sans-serif" font-size="{row_title_fs}px" font-weight="700" fill="#F7F1E7">Persistent Document Memory</text>
      <text x="{int(52*scale)}" y="{int(badge_h * 0.155)}" class="card-item-a">Deterministic index, content hashes &amp; action ledgers</text>
    </g>

    <!-- Row 3: Bounded & Verified -->
    <g transform="translate({int(22*scale)}, {int(badge_h * 0.65)})">
      <rect width="{badge_w - int(44*scale)}" height="{int(badge_h * 0.22)}" rx="{max(8, int(12*scale))}" fill="#041E26" fill-opacity="0.75" stroke="#073B49" stroke-width="1.2"/>
      <circle cx="{int(26*scale)}" cy="{int(badge_h * 0.11)}" r="{max(9, int(13*scale))}" fill="#073B49"/>
      <text x="{int(26*scale)}" y="{int(badge_h * 0.11) + int(5*scale)}" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="{card_num_fs}px" font-weight="700" fill="#5AD2D0">3</text>
      <text x="{int(52*scale)}" y="{int(badge_h * 0.085)}" font-family="'Segoe UI', sans-serif" font-size="{row_title_fs}px" font-weight="700" fill="#F7F1E7">Local Evidence Verifier</text>
      <text x="{int(52*scale)}" y="{int(badge_h * 0.155)}" class="card-item-a">Exact quotes &amp; citations verified before memory commit</text>
    </g>

    <!-- Bottom Badge Summary -->
    <g transform="translate({int(22*scale)}, {badge_h - max(36, int(52*scale))})">
      <rect width="{badge_w - int(44*scale)}" height="{max(30, int(38*scale))}" rx="{max(6, int(10*scale))}" fill="#0B4A59" fill-opacity="0.5" stroke="#1F9D72" stroke-width="1.2" stroke-dasharray="5 3"/>
      <text x="{int((badge_w - 44*scale)/2)}" y="{max(20, int(24*scale))}" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="{badge_summary_fs}px" font-weight="700" fill="#5AD2D0">REVERSIBLE ACTIONS · AUDITABLE RUNS</text>
    </g>
  </g>
</svg>"""
    return svg

# ==============================================================================
# CONCEPT B — evidence-ledger
# ==============================================================================
def get_concept_b_svg(width, height, variant_name):
    scale = width / 1600.0

    if variant_name == "banner":
        pad_x = 90
        pad_y = 90
        eb_w = 380
        prod_y = pad_y + 115
        hl_y1 = pad_y + 205
        hl_y2 = pad_y + 280
        sup_y = pad_y + 360
        chip_y = pad_y + 440
        chip_w = 230
        badge_x = 920
        badge_y = 100
        badge_w = 600
        eb_fs = 14
        prod_fs = 46
        hl_fs = 62
        sup_fs = 23
        chip_fs = 17
        bullet_fs = 15.5
        bullet_spacing = 38
    elif variant_name == "thumbnail":
        pad_x = 72
        pad_y = 65
        eb_w = 310
        prod_y = pad_y + 90
        hl_y1 = pad_y + 165
        hl_y2 = pad_y + 225
        sup_y = pad_y + 290
        chip_y = pad_y + 355
        chip_w = 190
        badge_x = 735
        badge_y = 75
        badge_w = 480
        eb_fs = 12
        prod_fs = 38
        hl_fs = 49
        sup_fs = 18.5
        chip_fs = 14
        bullet_fs = 13
        bullet_spacing = 32
    else: # social 1200 x 630
        pad_x = 64
        pad_y = 55
        eb_w = 295
        prod_y = pad_y + 80
        hl_y1 = pad_y + 148
        hl_y2 = pad_y + 204
        sup_y = pad_y + 262
        chip_y = pad_y + 322
        chip_w = 185
        badge_x = 690
        badge_y = 60
        badge_w = 460
        eb_fs = 11.5
        prod_fs = 36
        hl_fs = 45
        sup_fs = 17.5
        chip_fs = 13.5
        bullet_fs = 12
        bullet_spacing = 28

    # Render right cards based on variant
    if variant_name == "banner":
        right_cards_svg = f"""
    <!-- Card 1 (Top Layer): Evidence & Citation Structural Contract -->
    <g transform="translate(0, 0)" filter="url(#topShadowB_{variant_name})">
      <rect width="{badge_w}" height="345" rx="16" fill="#FFFFFF" stroke="#D3C7B0" stroke-width="1.6"/>
      
      <!-- Card Header Bar -->
      <rect width="{badge_w}" height="50" rx="16" fill="#073B49"/>
      <rect y="34" width="{badge_w}" height="16" fill="#073B49"/>
      
      <text x="22" y="32" font-family="'Segoe UI', sans-serif" font-size="14px" font-weight="700" fill="#F7F1E7" letter-spacing="1px">EVIDENCE STRUCTURE &amp; CITATION CONTRACT</text>
      
      <!-- Header Pill Badge -->
      <g transform="translate({badge_w - 155}, 11)">
        <rect width="135" height="28" rx="14" fill="#FF6B4A"/>
        <text x="67.5" y="18.5" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="11px" font-weight="700" fill="#FFFFFF" letter-spacing="0.5px">LOCAL EVIDENCE</text>
      </g>

      <!-- Field 1: QUESTION -->
      <g transform="translate(20, 66)">
        <rect width="{badge_w - 40}" height="48" rx="6" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        <rect x="10" y="8" width="80" height="18" rx="3" fill="#073B49"/>
        <text x="50" y="21" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#F7F1E7" letter-spacing="0.5px">QUESTION</text>
        <text x="98" y="22" font-family="'Segoe UI', sans-serif" font-size="12.5px" font-weight="600" fill="#0F172A">Document query scoped to explicitly approved folders</text>
        <text x="10" y="40" font-family="'Segoe UI', sans-serif" font-size="11.5px" fill="#64748B">Structured query input with multi-question coverage analysis</text>
      </g>

      <!-- Field 2: SELECTED SOURCE CHUNK -->
      <g transform="translate(20, 122)">
        <rect width="{badge_w - 40}" height="48" rx="6" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        <rect x="10" y="8" width="165" height="18" rx="3" fill="#0B4A59"/>
        <text x="92.5" y="21" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#F7F1E7" letter-spacing="0.5px">SELECTED SOURCE CHUNK</text>
        <text x="184" y="22" font-family="'Segoe UI', sans-serif" font-size="12.5px" font-weight="600" fill="#0F172A">Bounded context with character offsets</text>
        <text x="10" y="40" font-family="'Segoe UI', sans-serif" font-size="11.5px" fill="#64748B">Local extraction with source IDs, character offsets and chunk boundaries</text>
      </g>

      <!-- Field 3: EXACT QUOTE + SOURCE LOCATION -->
      <g transform="translate(20, 178)">
        <rect width="{badge_w - 40}" height="100" rx="8" fill="#FAF8F5" stroke="#E2D7C3" stroke-width="1.2"/>
        <rect x="0" y="0" width="5" height="100" fill="#FF6B4A" rx="2.5"/>
        
        <g transform="translate(16, 12)">
          <rect width="210" height="22" rx="4" fill="#FF6B4A" fill-opacity="0.15" stroke="#FF6B4A" stroke-width="1"/>
          <text x="105" y="15.5" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="11px" font-weight="800" fill="#C2410C" letter-spacing="0.5px">EXACT QUOTE + SOURCE LOCATION</text>
        </g>
        
        <text x="16" y="54" font-family="Georgia, serif" font-size="13.5px" font-style="italic" fill="#0F172A">Verifiable verbatim passage pinned to source ID and line or page range</text>
        <text x="16" y="74" font-family="'Segoe UI', sans-serif" font-size="12px" fill="#64748B">Every promoted claim keeps an exact quote and source locator</text>
        
        <!-- Pill on bottom right: CONFLICT HINTS STAY VISIBLE -->
        <g transform="translate({badge_w - 245}, 66)">
          <rect width="195" height="24" rx="12" fill="#FEF3C7" stroke="#F59E0B" stroke-width="1"/>
          <circle cx="12" cy="12" r="3.5" fill="#D97706"/>
          <text x="22" y="16" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#92400E" letter-spacing="0.3px">CONFLICT HINTS STAY VISIBLE</text>
        </g>
      </g>

      <!-- Bottom Card 1 Footer: PERSISTENT LOCAL INDEX -->
      <g transform="translate(20, 294)">
        <rect width="{badge_w - 40}" height="36" rx="6" fill="#E8F8F0" stroke="#1F9D72" stroke-width="1"/>
        <circle cx="18" cy="18" r="5" fill="#1F9D72"/>
        <text x="32" y="22.5" font-family="'Segoe UI', sans-serif" font-size="12.5px" font-weight="700" fill="#065F46" letter-spacing="0.5px">PERSISTENT LOCAL INDEX</text>
        <text x="{badge_w - 55}" y="22.5" text-anchor="end" font-family="'Segoe UI', sans-serif" font-size="12px" font-weight="600" fill="#047857">LOCAL VERIFICATION CORE</text>
      </g>
    </g>

    <!-- Card 2 (Bottom Layer): Coverage & Report Contract -->
    <g transform="translate(0, 365)" filter="url(#cardShadowB_{variant_name})">
      <rect width="{badge_w}" height="300" rx="16" fill="#FFFFFF" stroke="#D3C7B0" stroke-width="1.6"/>
      
      <!-- Ledger Header -->
      <g transform="translate(20, 22)">
        <text font-family="'Segoe UI', sans-serif" font-size="13.5px" font-weight="800" fill="#073B49" letter-spacing="0.8px">COVERAGE MATRIX &amp; EXPORT CONTRACT</text>
        <line x1="0" y1="14" x2="{badge_w - 40}" y2="14" stroke="#E2D7C3" stroke-width="1"/>
      </g>

      <!-- Item 1: COVERAGE: READ · CITED · UNSUPPORTED · UNREADABLE -->
      <g transform="translate(20, 50)">
        <rect width="{badge_w - 40}" height="102" rx="8" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        
        <g transform="translate(12, 10)">
          <rect width="340" height="22" rx="4" fill="#073B49"/>
          <text x="170" y="15.5" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#F7F1E7" letter-spacing="0.5px">COVERAGE: READ · CITED · UNSUPPORTED · UNREADABLE</text>
        </g>
        
        <text x="12" y="52" font-family="'Segoe UI', sans-serif" font-size="12.5px" font-weight="600" fill="#0F172A">Auditable folder coverage accounting without silent omissions</text>
        <text x="12" y="72" font-family="'Segoe UI', sans-serif" font-size="11.5px" fill="#64748B">Explicit classification for every scanned file in the approved workspace</text>
        <text x="12" y="91" font-family="'Segoe UI', sans-serif" font-size="11.5px" font-weight="600" fill="#1F9D72">✓ Run ledger and action journal stay local</text>
      </g>

      <!-- Item 2: REPORT CONTRACT → MD · TXT · PDF · DOCX · ODT -->
      <g transform="translate(20, 166)">
        <rect width="{badge_w - 40}" height="114" rx="8" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        
        <g transform="translate(12, 10)">
          <rect width="300" height="22" rx="4" fill="#0B4A59"/>
          <text x="150" y="15.5" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#F7F1E7" letter-spacing="0.5px">REPORT CONTRACT → MD · TXT · PDF · DOCX · ODT</text>
        </g>
        
        <text x="12" y="52" font-family="'Segoe UI', sans-serif" font-size="12.5px" font-weight="600" fill="#0F172A">Validated multi-format export with exact quotes and source locations</text>
        <text x="12" y="72" font-family="'Segoe UI', sans-serif" font-size="11.5px" fill="#64748B">Structured outputs for reports, receipts, and run ledgers</text>
        <text x="12" y="94" font-family="'Segoe UI', sans-serif" font-size="11.5px" font-weight="600" fill="#FF6B4A">⚡ Reversible file operations with pre-execution safety gates</text>
      </g>
    </g>"""
    elif variant_name == "thumbnail":
        # Simplified for 1280x720 thumbnail: no font < 10px, 1 concise description per row
        right_cards_svg = f"""
    <!-- Card 1: Evidence & Citation Structural Contract (Simplified Thumbnail) -->
    <g transform="translate(0, 0)" filter="url(#topShadowB_{variant_name})">
      <rect width="{badge_w}" height="280" rx="14" fill="#FFFFFF" stroke="#D3C7B0" stroke-width="1.5"/>
      
      <!-- Card Header Bar -->
      <rect width="{badge_w}" height="42" rx="14" fill="#073B49"/>
      <rect y="28" width="{badge_w}" height="14" fill="#073B49"/>
      
      <text x="18" y="27" font-family="'Segoe UI', sans-serif" font-size="12.5px" font-weight="700" fill="#F7F1E7" letter-spacing="0.8px">EVIDENCE STRUCTURE &amp; CITATION CONTRACT</text>
      
      <!-- Field 1: QUESTION -->
      <g transform="translate(16, 54)">
        <rect width="{badge_w - 32}" height="38" rx="6" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        <rect x="8" y="8" width="76" height="22" rx="4" fill="#073B49"/>
        <text x="46" y="23" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#F7F1E7" letter-spacing="0.5px">QUESTION</text>
        <text x="92" y="23.5" font-family="'Segoe UI', sans-serif" font-size="11.5px" font-weight="600" fill="#0F172A">Document query scoped to explicitly approved folders</text>
      </g>

      <!-- Field 2: SELECTED SOURCE CHUNK -->
      <g transform="translate(16, 100)">
        <rect width="{badge_w - 32}" height="38" rx="6" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        <rect x="8" y="8" width="158" height="22" rx="4" fill="#0B4A59"/>
        <text x="87" y="23" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#F7F1E7" letter-spacing="0.5px">SELECTED SOURCE CHUNK</text>
        <text x="174" y="23.5" font-family="'Segoe UI', sans-serif" font-size="11.5px" font-weight="600" fill="#0F172A">Bounded context with character offsets</text>
      </g>

      <!-- Field 3: EXACT QUOTE + SOURCE LOCATION -->
      <g transform="translate(16, 146)">
        <rect width="{badge_w - 32}" height="76" rx="8" fill="#FAF8F5" stroke="#E2D7C3" stroke-width="1.2"/>
        <rect x="0" y="0" width="4" height="76" fill="#FF6B4A" rx="2"/>
        
        <g transform="translate(12, 10)">
          <rect width="200" height="20" rx="4" fill="#FF6B4A" fill-opacity="0.15" stroke="#FF6B4A" stroke-width="1"/>
          <text x="100" y="14.5" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="800" fill="#C2410C" letter-spacing="0.4px">EXACT QUOTE + SOURCE LOCATION</text>
        </g>
        
        <text x="12" y="47" font-family="Georgia, serif" font-size="12px" font-style="italic" fill="#0F172A">Verifiable passage pinned to source ID and line or page range</text>
        <text x="12" y="66" font-family="'Segoe UI', sans-serif" font-size="11px" fill="#64748B">Every promoted claim keeps an exact quote and source locator</text>
      </g>

      <!-- Bottom Card 1 Footer -->
      <g transform="translate(16, 234)">
        <rect width="{badge_w - 32}" height="32" rx="6" fill="#E8F8F0" stroke="#1F9D72" stroke-width="1"/>
        <circle cx="16" cy="16" r="4.5" fill="#1F9D72"/>
        <text x="28" y="20.5" font-family="'Segoe UI', sans-serif" font-size="11px" font-weight="700" fill="#065F46" letter-spacing="0.4px">PERSISTENT LOCAL INDEX</text>
        <text x="{badge_w - 44}" y="20.5" text-anchor="end" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="600" fill="#047857">CONFLICT HINTS STAY VISIBLE</text>
      </g>
    </g>

    <!-- Card 2: Coverage Matrix & Report Contract (Simplified Thumbnail) -->
    <g transform="translate(0, 296)" filter="url(#cardShadowB_{variant_name})">
      <rect width="{badge_w}" height="255" rx="14" fill="#FFFFFF" stroke="#D3C7B0" stroke-width="1.5"/>
      
      <!-- Ledger Header -->
      <g transform="translate(16, 18)">
        <text font-family="'Segoe UI', sans-serif" font-size="12px" font-weight="800" fill="#073B49" letter-spacing="0.7px">COVERAGE MATRIX &amp; EXPORT CONTRACT</text>
        <line x1="0" y1="12" x2="{badge_w - 32}" y2="12" stroke="#E2D7C3" stroke-width="1"/>
      </g>

      <!-- Item 1: COVERAGE -->
      <g transform="translate(16, 42)">
        <rect width="{badge_w - 32}" height="90" rx="8" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        
        <g transform="translate(10, 8)">
          <rect width="320" height="20" rx="4" fill="#073B49"/>
          <text x="160" y="14.5" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#F7F1E7" letter-spacing="0.4px">COVERAGE: READ · CITED · UNSUPPORTED · UNREADABLE</text>
        </g>
        
        <text x="10" y="44" font-family="'Segoe UI', sans-serif" font-size="11.5px" font-weight="600" fill="#0F172A">Auditable folder coverage accounting without silent omissions</text>
        <text x="10" y="62" font-family="'Segoe UI', sans-serif" font-size="11px" fill="#64748B">Explicit classification for every scanned file in approved workspace</text>
        <text x="10" y="80" font-family="'Segoe UI', sans-serif" font-size="11px" font-weight="600" fill="#1F9D72">✓ Run ledger and action journal stay local</text>
      </g>

      <!-- Item 2: REPORT CONTRACT -->
      <g transform="translate(16, 142)">
        <rect width="{badge_w - 32}" height="98" rx="8" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        
        <g transform="translate(10, 8)">
          <rect width="280" height="20" rx="4" fill="#0B4A59"/>
          <text x="140" y="14.5" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#F7F1E7" letter-spacing="0.4px">REPORT CONTRACT → MD · TXT · PDF · DOCX · ODT</text>
        </g>
        
        <text x="10" y="44" font-family="'Segoe UI', sans-serif" font-size="11.5px" font-weight="600" fill="#0F172A">Validated multi-format export with exact quotes and source locations</text>
        <text x="10" y="64" font-family="'Segoe UI', sans-serif" font-size="11px" fill="#64748B">Structured outputs for reports, receipts, and run ledgers</text>
        <text x="10" y="84" font-family="'Segoe UI', sans-serif" font-size="11px" font-weight="600" fill="#FF6B4A">⚡ Reversible file operations with safety gates</text>
      </g>
    </g>"""
    else:
        # Simplified for 1200x630 social: no font < 10px, 1 concise description per row
        right_cards_svg = f"""
    <!-- Card 1: Evidence & Citation Structural Contract (Simplified Social) -->
    <g transform="translate(0, 0)" filter="url(#topShadowB_{variant_name})">
      <rect width="{badge_w}" height="250" rx="12" fill="#FFFFFF" stroke="#D3C7B0" stroke-width="1.5"/>
      
      <!-- Card Header Bar -->
      <rect width="{badge_w}" height="38" rx="12" fill="#073B49"/>
      <rect y="26" width="{badge_w}" height="12" fill="#073B49"/>
      
      <text x="16" y="25" font-family="'Segoe UI', sans-serif" font-size="12px" font-weight="700" fill="#F7F1E7" letter-spacing="0.7px">EVIDENCE STRUCTURE &amp; CITATION CONTRACT</text>
      
      <!-- Field 1: QUESTION -->
      <g transform="translate(14, 48)">
        <rect width="{badge_w - 28}" height="34" rx="5" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        <rect x="8" y="7" width="72" height="20" rx="3" fill="#073B49"/>
        <text x="44" y="21" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10px" font-weight="700" fill="#F7F1E7" letter-spacing="0.4px">QUESTION</text>
        <text x="86" y="21.5" font-family="'Segoe UI', sans-serif" font-size="11px" font-weight="600" fill="#0F172A">Document query scoped to explicitly approved folders</text>
      </g>

      <!-- Field 2: SELECTED SOURCE CHUNK -->
      <g transform="translate(14, 88)">
        <rect width="{badge_w - 28}" height="34" rx="5" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        <rect x="8" y="7" width="150" height="20" rx="3" fill="#0B4A59"/>
        <text x="83" y="21" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10px" font-weight="700" fill="#F7F1E7" letter-spacing="0.4px">SELECTED SOURCE CHUNK</text>
        <text x="165" y="21.5" font-family="'Segoe UI', sans-serif" font-size="11px" font-weight="600" fill="#0F172A">Bounded context with character offsets</text>
      </g>

      <!-- Field 3: EXACT QUOTE + SOURCE LOCATION -->
      <g transform="translate(14, 128)">
        <rect width="{badge_w - 28}" height="70" rx="6" fill="#FAF8F5" stroke="#E2D7C3" stroke-width="1.2"/>
        <rect x="0" y="0" width="4" height="70" fill="#FF6B4A" rx="2"/>
        
        <g transform="translate(10, 8)">
          <rect width="190" height="18" rx="3" fill="#FF6B4A" fill-opacity="0.15" stroke="#FF6B4A" stroke-width="1"/>
          <text x="95" y="13.5" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10px" font-weight="800" fill="#C2410C" letter-spacing="0.3px">EXACT QUOTE + SOURCE LOCATION</text>
        </g>
        
        <text x="10" y="42" font-family="Georgia, serif" font-size="11.5px" font-style="italic" fill="#0F172A">Verifiable passage pinned to source ID and line or page range</text>
        <text x="10" y="59" font-family="'Segoe UI', sans-serif" font-size="10.5px" fill="#64748B">Every promoted claim keeps an exact quote and source locator</text>
      </g>

      <!-- Bottom Card 1 Footer -->
      <g transform="translate(14, 206)">
        <rect width="{badge_w - 28}" height="30" rx="5" fill="#E8F8F0" stroke="#1F9D72" stroke-width="1"/>
        <circle cx="14" cy="15" r="4" fill="#1F9D72"/>
        <text x="24" y="19" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="700" fill="#065F46" letter-spacing="0.3px">PERSISTENT LOCAL INDEX</text>
        <text x="{badge_w - 38}" y="19" text-anchor="end" font-family="'Segoe UI', sans-serif" font-size="10px" font-weight="600" fill="#047857">CONFLICT HINTS STAY VISIBLE</text>
      </g>
    </g>

    <!-- Card 2: Coverage Matrix & Report Contract (Simplified Social) -->
    <g transform="translate(0, 262)" filter="url(#cardShadowB_{variant_name})">
      <rect width="{badge_w}" height="236" rx="12" fill="#FFFFFF" stroke="#D3C7B0" stroke-width="1.5"/>
      
      <!-- Ledger Header -->
      <g transform="translate(14, 16)">
        <text font-family="'Segoe UI', sans-serif" font-size="11.5px" font-weight="800" fill="#073B49" letter-spacing="0.6px">COVERAGE MATRIX &amp; EXPORT CONTRACT</text>
        <line x1="0" y1="10" x2="{badge_w - 28}" y2="10" stroke="#E2D7C3" stroke-width="1"/>
      </g>

      <!-- Item 1: COVERAGE -->
      <g transform="translate(14, 36)">
        <rect width="{badge_w - 28}" height="84" rx="6" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        
        <g transform="translate(8, 7)">
          <rect width="300" height="18" rx="3" fill="#073B49"/>
          <text x="150" y="13.5" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10px" font-weight="700" fill="#F7F1E7" letter-spacing="0.3px">COVERAGE: READ · CITED · UNSUPPORTED · UNREADABLE</text>
        </g>
        
        <text x="8" y="40" font-family="'Segoe UI', sans-serif" font-size="11px" font-weight="600" fill="#0F172A">Auditable folder coverage accounting without silent omissions</text>
        <text x="8" y="57" font-family="'Segoe UI', sans-serif" font-size="10.5px" fill="#64748B">Explicit classification for every scanned file in approved workspace</text>
        <text x="8" y="74" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="600" fill="#1F9D72">✓ Run ledger and action journal stay local</text>
      </g>

      <!-- Item 2: REPORT CONTRACT -->
      <g transform="translate(14, 128)">
        <rect width="{badge_w - 28}" height="94" rx="6" fill="#F9F6F0" stroke="#E6DEC9" stroke-width="1"/>
        
        <g transform="translate(8, 7)">
          <rect width="265" height="18" rx="3" fill="#0B4A59"/>
          <text x="132.5" y="13.5" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="10px" font-weight="700" fill="#F7F1E7" letter-spacing="0.3px">REPORT CONTRACT → MD · TXT · PDF · DOCX · ODT</text>
        </g>
        
        <text x="8" y="40" font-family="'Segoe UI', sans-serif" font-size="11px" font-weight="600" fill="#0F172A">Validated multi-format export with exact quotes and source locations</text>
        <text x="8" y="58" font-family="'Segoe UI', sans-serif" font-size="10.5px" fill="#64748B">Structured outputs for reports, receipts, and run ledgers</text>
        <text x="8" y="78" font-family="'Segoe UI', sans-serif" font-size="10.5px" font-weight="600" fill="#FF6B4A">⚡ Reversible file operations with safety gates</text>
      </g>
    </g>"""

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="NemoFold - Evidence Ledger">
  <defs>
    <!-- Background Grid Pattern -->
    <pattern id="gridB_{variant_name}" width="{max(24, int(32*scale))}" height="{max(24, int(32*scale))}" patternUnits="userSpaceOnUse">
      <path d="M {max(24, int(32*scale))} 0 L 0 0 0 {max(24, int(32*scale))}" fill="none" stroke="#E6DEC9" stroke-width="0.8"/>
      <circle cx="0" cy="0" r="1.2" fill="#D5CABA"/>
    </pattern>
    <filter id="topShadowB_{variant_name}" x="-10%" y="-10%" width="125%" height="125%">
      <feDropShadow dx="0" dy="16" stdDeviation="20" flood-color="#073B49" flood-opacity="0.12"/>
      <feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#0F172A" flood-opacity="0.06"/>
    </filter>
    <filter id="cardShadowB_{variant_name}" x="-10%" y="-10%" width="125%" height="125%">
      <feDropShadow dx="0" dy="12" stdDeviation="16" flood-color="#0F172A" flood-opacity="0.08"/>
    </filter>
    <linearGradient id="coralGradB_{variant_name}" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#FF6B4A"/>
      <stop offset="100%" stop-color="#FA8C73"/>
    </linearGradient>
    <style>
      .eb-text-b {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {eb_fs}px; font-weight: 700; fill: #073B49; letter-spacing: 2px; text-transform: uppercase; }}
      .prod-text-b {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {prod_fs}px; font-weight: 800; fill: #073B49; letter-spacing: -0.5px; }}
      .prod-sub-b {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {prod_fs}px; font-weight: 800; fill: #FF6B4A; }}
      .hl-text-b {{ font-family: Georgia, 'Times New Roman', serif; font-size: {hl_fs}px; font-weight: 700; fill: #0F172A; letter-spacing: -0.5px; line-height: 1.15; }}
      .sup-text-b {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {sup_fs}px; font-weight: 400; fill: #334155; letter-spacing: 0.2px; }}
      .chip-text-b {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {chip_fs}px; font-weight: 700; fill: #065F46; letter-spacing: 0.3px; }}
    </style>
  </defs>

  <!-- 1. Warm Ivory Canvas -->
  <rect width="{width}" height="{height}" fill="#F7F1E7"/>
  <rect width="{width}" height="{height}" fill="url(#gridB_{variant_name})"/>

  <!-- Left/Top Brand Borders -->
  <rect x="0" y="0" width="{max(4, int(6*scale))}" height="{height}" fill="#073B49"/>
  <rect x="0" y="0" width="{width}" height="{max(3, int(4*scale))}" fill="url(#coralGradB_{variant_name})"/>

  <!-- 2. Left Column: Text & Brand -->
  <!-- Eyebrow Pill -->
  <g transform="translate({pad_x}, {pad_y})">
    <rect x="0" y="0" width="{eb_w}" height="{max(26, int(32*scale))}" rx="{max(6, int(8*scale))}" fill="#FFFFFF" stroke="#D3C7B0" stroke-width="1.2"/>
    <circle cx="{int(16*scale)}" cy="{max(13, int(16*scale))}" r="{max(3.5, 4.5*scale)}" fill="#FF6B4A"/>
    <text x="{int(32*scale)}" y="{max(17, int(21*scale))}" class="eb-text-b">EVIDENCE-FIRST DOCUMENT AGENT</text>
  </g>

  <!-- Product Brand Mark & Name -->
  <g transform="translate({pad_x}, {prod_y})">
    <!-- Origami Fold Icon in Dark / Coral -->
    <g transform="scale({scale * 0.95})">
      <path d="M0,0 L24,-14 L42,6 L18,20 Z" fill="#073B49"/>
      <path d="M18,20 L42,6 L36,36 L12,48 Z" fill="#FF6B4A"/>
      <path d="M0,0 L18,20 L12,48 L-6,26 Z" fill="#1F9D72"/>
    </g>
    <text x="{int(58*scale)}" y="{int(32*scale)}" class="prod-text-b">Nemo<tspan class="prod-sub-b">Fold</tspan></text>
  </g>

  <!-- Headline -->
  <text x="{pad_x}" y="{hl_y1}" class="hl-text-b">Answers that point</text>
  <text x="{pad_x}" y="{hl_y2}" class="hl-text-b">back to the page.</text>

  <!-- Supporting Copy -->
  <text x="{pad_x}" y="{sup_y}" class="sup-text-b">Exact quotes. Source locations. Coverage you can inspect.</text>

  <!-- Status Chip: Local core ready -->
  <g transform="translate({pad_x}, {chip_y})">
    <rect x="0" y="0" width="{chip_w}" height="{max(36, int(46*scale))}" rx="{max(18, int(23*scale))}" fill="#E8F8F0" stroke="#1F9D72" stroke-width="1.8"/>
    <!-- Emerald Shield Icon -->
    <circle cx="{int(24*scale)}" cy="{max(18, int(23*scale))}" r="{max(7, int(9*scale))}" fill="#1F9D72"/>
    <path d="M{int(20*scale)},{max(18, int(23*scale))} L{int(23*scale)},{max(21, int(26*scale))} L{int(28*scale)},{max(15, int(20*scale))}" fill="none" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round"/>
    <text x="{int(42*scale)}" y="{max(23, int(29.5*scale))}" class="chip-text-b">Local core ready</text>
  </g>

  <!-- Safe Trust Bullet Highlights -->
  <g transform="translate({pad_x}, {chip_y + int(65*scale)})">
    <g transform="translate(0, 0)">
      <circle cx="{int(9*scale)}" cy="{int(9*scale)}" r="{max(6, int(8*scale))}" fill="#073B49"/>
      <path d="M{int(6*scale)},{int(9*scale)} L{int(8*scale)},{int(11.5*scale)} L{int(12*scale)},{int(6.5*scale)}" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round"/>
      <text x="{int(26*scale)}" y="{int(13.5*scale)}" font-family="'Segoe UI', sans-serif" font-size="{bullet_fs}px" font-weight="600" fill="#073B49">Multiple questions · Exact quotes · Source locations</text>
    </g>
    <g transform="translate(0, {bullet_spacing})">
      <circle cx="{int(9*scale)}" cy="{int(9*scale)}" r="{max(6, int(8*scale))}" fill="#073B49"/>
      <path d="M{int(6*scale)},{int(9*scale)} L{int(8*scale)},{int(11.5*scale)} L{int(12*scale)},{int(6.5*scale)}" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round"/>
      <text x="{int(26*scale)}" y="{int(13.5*scale)}" font-family="'Segoe UI', sans-serif" font-size="{bullet_fs}px" font-weight="600" fill="#073B49">Coverage keeps unsupported and unreadable files visible</text>
    </g>
    <g transform="translate(0, {bullet_spacing * 2})">
      <circle cx="{int(9*scale)}" cy="{int(9*scale)}" r="{max(6, int(8*scale))}" fill="#073B49"/>
      <path d="M{int(6*scale)},{int(9*scale)} L{int(8*scale)},{int(11.5*scale)} L{int(12*scale)},{int(6.5*scale)}" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round"/>
      <text x="{int(26*scale)}" y="{int(13.5*scale)}" font-family="'Segoe UI', sans-serif" font-size="{bullet_fs}px" font-weight="600" fill="#073B49">Persistent inventory and local full-text index</text>
    </g>
  </g>

  <!-- 3. Right Column: Layered Evidence Board -->
  <g transform="translate({badge_x}, {badge_y})">
    {right_cards_svg}
  </g>
</svg>"""
    return svg

# ==============================================================================
# CONCEPT C — bounded-reasoning
# ==============================================================================
def get_concept_c_svg(width, height, variant_name):
    scale = width / 1600.0

    if variant_name == "banner":
        pad_x = 90
        pad_y = 90
        eb_w = 440
        prod_y = pad_y + 115
        hl_y1 = pad_y + 205
        hl_y2 = pad_y + 280
        sup_y = pad_y + 360
        chip_y = pad_y + 440
        chip_w = 260
        badge_x = 880
        badge_y = 110
        badge_w = 640
        badge_h = 680
        eb_fs = 14
        prod_fs = 46
        hl_fs = 58
        sup_fs = 23
        chip_fs = 17
        inv_fs = 16
        inv_spacing = 40
        local_hdr_fs = 13.5
        local_title_fs = 15
        local_desc_fs = 13
        guar_fs = 12.5
        cloud_hdr_fs = 12
        cloud_model_fs = 14.5
        cloud_sub_fs = 13.5
        cloud_item_fs = 13
        ret_hdr_fs = 11
        ret_sub_fs = 11.5
    elif variant_name == "thumbnail":
        pad_x = 72
        pad_y = 65
        eb_w = 360
        prod_y = pad_y + 90
        hl_y1 = pad_y + 165
        hl_y2 = pad_y + 225
        sup_y = pad_y + 290
        chip_y = pad_y + 355
        chip_w = 215
        badge_x = 705
        badge_y = 85
        badge_w = 515
        badge_h = 550
        eb_fs = 12
        prod_fs = 38
        hl_fs = 46
        sup_fs = 18.5
        chip_fs = 14
        inv_fs = 13
        inv_spacing = 34
        local_hdr_fs = 11.5
        local_title_fs = 12.5
        local_desc_fs = 11
        guar_fs = 10.5
        cloud_hdr_fs = 10.5
        cloud_model_fs = 12
        cloud_sub_fs = 11
        cloud_item_fs = 11
        ret_hdr_fs = 10
        ret_sub_fs = 10.5
    else: # social 1200 x 630
        pad_x = 64
        pad_y = 55
        eb_w = 345
        prod_y = pad_y + 80
        hl_y1 = pad_y + 148
        hl_y2 = pad_y + 204
        sup_y = pad_y + 262
        chip_y = pad_y + 322
        chip_w = 205
        badge_x = 660
        badge_y = 70
        badge_w = 480
        badge_h = 490
        eb_fs = 11.5
        prod_fs = 36
        hl_fs = 42
        sup_fs = 17.5
        chip_fs = 13.5
        inv_fs = 12
        inv_spacing = 30
        local_hdr_fs = 11
        local_title_fs = 12
        local_desc_fs = 10.5
        guar_fs = 10
        cloud_hdr_fs = 10
        cloud_model_fs = 11.5
        cloud_sub_fs = 10.5
        cloud_item_fs = 10.5
        ret_hdr_fs = 10
        ret_sub_fs = 10
    
    local_box_w = int(badge_w * 0.56)
    cloud_box_w = int(badge_w * 0.34)
    cloud_box_x = int(badge_w * 0.63)
    divider_x = int(badge_w * 0.605)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="NemoFold - Bounded Reasoning">
  <defs>
    <!-- Background Gradients -->
    <linearGradient id="bgGradC_{variant_name}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#021218"/>
      <stop offset="50%" stop-color="#072F3A"/>
      <stop offset="100%" stop-color="#031A22"/>
    </linearGradient>
    <linearGradient id="localCardGradC_{variant_name}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0B4A59" stop-opacity="0.95"/>
      <stop offset="100%" stop-color="#06323E" stop-opacity="0.95"/>
    </linearGradient>
    <linearGradient id="cloudCardGradC_{variant_name}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1E1B4B" stop-opacity="0.95"/>
      <stop offset="100%" stop-color="#0F172A" stop-opacity="0.95"/>
    </linearGradient>
    <filter id="shadowC_{variant_name}" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="16" stdDeviation="22" flood-color="#000000" flood-opacity="0.65"/>
    </filter>
    <filter id="glowCyanC_{variant_name}" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="5" result="blur"/>
      <feComposite in="SourceGraphic" in2="blur" operator="over"/>
    </filter>
    <style>
      .eb-text-c {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {eb_fs}px; font-weight: 700; fill: #5AD2D0; letter-spacing: 2px; text-transform: uppercase; }}
      .prod-text-c {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {prod_fs}px; font-weight: 800; fill: #F7F1E7; letter-spacing: -0.5px; }}
      .prod-sub-c {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {prod_fs}px; font-weight: 800; fill: #5AD2D0; }}
      .hl-text-c {{ font-family: Georgia, 'Times New Roman', serif; font-size: {hl_fs}px; font-weight: 700; fill: #F7F1E7; letter-spacing: -0.5px; line-height: 1.15; }}
      .sup-text-c {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {sup_fs}px; font-weight: 400; fill: #C8E3E1; letter-spacing: 0.2px; }}
      .chip-text-c {{ font-family: 'Segoe UI', Arial, -apple-system, sans-serif; font-size: {chip_fs}px; font-weight: 700; fill: #FBBF24; letter-spacing: 0.3px; }}
    </style>
  </defs>

  <!-- 1. Dark Architecture Canvas -->
  <rect width="{width}" height="{height}" fill="url(#bgGradC_{variant_name})"/>
  
  <!-- Subtle Blueprint Grid Lines -->
  <g opacity="0.12">
    <line x1="0" y1="{int(height*0.25)}" x2="{width}" y2="{int(height*0.25)}" stroke="#5AD2D0" stroke-width="1"/>
    <line x1="0" y1="{int(height*0.50)}" x2="{width}" y2="{int(height*0.50)}" stroke="#5AD2D0" stroke-width="1"/>
    <line x1="0" y1="{int(height*0.75)}" x2="{width}" y2="{int(height*0.75)}" stroke="#5AD2D0" stroke-width="1"/>
    <line x1="{int(width*0.25)}" y1="0" x2="{int(width*0.25)}" y2="{height}" stroke="#5AD2D0" stroke-width="1"/>
    <line x1="{int(width*0.50)}" y1="0" x2="{int(width*0.50)}" y2="{height}" stroke="#5AD2D0" stroke-width="1"/>
    <line x1="{int(width*0.75)}" y1="0" x2="{int(width*0.75)}" y2="{height}" stroke="#5AD2D0" stroke-width="1"/>
  </g>

  <!-- Top Accent Bar -->
  <rect x="0" y="0" width="{width}" height="{max(3, int(4*scale))}" fill="#5AD2D0"/>

  <!-- 2. Left Column: Text & Brand -->
  <!-- Eyebrow Pill -->
  <g transform="translate({pad_x}, {pad_y})">
    <rect x="0" y="0" width="{eb_w}" height="{max(26, int(32*scale))}" rx="{max(13, int(16*scale))}" fill="#073B49" stroke="#5AD2D0" stroke-width="1.2"/>
    <circle cx="{int(16*scale)}" cy="{max(13, int(16*scale))}" r="{max(3.5, 4.5*scale)}" fill="#5AD2D0"/>
    <text x="{int(32*scale)}" y="{max(17, int(21*scale))}" class="eb-text-c">LOCAL AUTHORITY · BOUNDED REASONING</text>
  </g>

  <!-- Product Brand Mark & Name -->
  <g transform="translate({pad_x}, {prod_y})">
    <g transform="scale({scale * 0.95})">
      <path d="M0,0 L24,-14 L42,6 L18,20 Z" fill="#FF6B4A"/>
      <path d="M18,20 L42,6 L36,36 L12,48 Z" fill="#5AD2D0"/>
      <path d="M0,0 L18,20 L12,48 L-6,26 Z" fill="#1F9D72"/>
    </g>
    <text x="{int(58*scale)}" y="{int(32*scale)}" class="prod-text-c">Nemo<tspan class="prod-sub-c">Fold</tspan></text>
  </g>

  <!-- Headline -->
  <text x="{pad_x}" y="{hl_y1}" class="hl-text-c">Reasoning may travel.</text>
  <text x="{pad_x}" y="{hl_y2}" class="hl-text-c">File authority stays local.</text>

  <!-- Supporting Copy -->
  <text x="{pad_x}" y="{sup_y}" class="sup-text-c">Explicit scope. Pseudonymized context. Local verification.</text>

  <!-- Status Chip: Cloud proof: pending -->
  <g transform="translate({pad_x}, {chip_y})">
    <rect x="0" y="0" width="{chip_w}" height="{max(36, int(46*scale))}" rx="{max(18, int(23*scale))}" fill="#1E293B" stroke="#F59E0B" stroke-width="1.8"/>
    <!-- Pending Amber Dot -->
    <circle cx="{int(24*scale)}" cy="{max(18, int(23*scale))}" r="{max(4.5, 6*scale)}" fill="#F59E0B"/>
    <text x="{int(42*scale)}" y="{max(23, int(29.5*scale))}" class="chip-text-c">Cloud proof: pending</text>
  </g>

  <!-- Key Architecture Invariants -->
  <g transform="translate({pad_x}, {chip_y + int(70*scale)})">
    <g transform="translate(0, 0)">
      <rect width="{max(20, int(24*scale))}" height="{max(20, int(24*scale))}" rx="{max(5, int(6*scale))}" fill="#0B4A59" stroke="#5AD2D0" stroke-width="1"/>
      <path d="M{max(6, int(7*scale))},{max(10, int(12*scale))} L{max(9, int(11*scale))},{max(14, int(16*scale))} L{max(15, int(17*scale))},{max(7, int(8*scale))}" fill="none" stroke="#5AD2D0" stroke-width="2" stroke-linecap="round"/>
      <text x="{max(28, int(36*scale))}" y="{max(14, int(17*scale))}" font-family="'Segoe UI', sans-serif" font-size="{inv_fs}px" font-weight="600" fill="#F7F1E7">Approved Folders: originals &amp; paths never leave disk</text>
    </g>
    <g transform="translate(0, {inv_spacing})">
      <rect width="{max(20, int(24*scale))}" height="{max(20, int(24*scale))}" rx="{max(5, int(6*scale))}" fill="#0B4A59" stroke="#5AD2D0" stroke-width="1"/>
      <path d="M{max(6, int(7*scale))},{max(10, int(12*scale))} L{max(9, int(11*scale))},{max(14, int(16*scale))} L{max(15, int(17*scale))},{max(7, int(8*scale))}" fill="none" stroke="#5AD2D0" stroke-width="2" stroke-linecap="round"/>
      <text x="{max(28, int(36*scale))}" y="{max(14, int(17*scale))}" font-family="'Segoe UI', sans-serif" font-size="{inv_fs}px" font-weight="600" fill="#F7F1E7">Policy &amp; Privacy Gate: fail-closed bounded budget</text>
    </g>
    <g transform="translate(0, {inv_spacing * 2})">
      <rect width="{max(20, int(24*scale))}" height="{max(20, int(24*scale))}" rx="{max(5, int(6*scale))}" fill="#0B4A59" stroke="#5AD2D0" stroke-width="1"/>
      <path d="M{max(6, int(7*scale))},{max(10, int(12*scale))} L{max(9, int(11*scale))},{max(14, int(16*scale))} L{max(15, int(17*scale))},{max(7, int(8*scale))}" fill="none" stroke="#5AD2D0" stroke-width="2" stroke-linecap="round"/>
      <text x="{max(28, int(36*scale))}" y="{max(14, int(17*scale))}" font-family="'Segoe UI', sans-serif" font-size="{inv_fs}px" font-weight="600" fill="#F7F1E7">Evidence Verifier: local schema &amp; quote validation</text>
    </g>
  </g>

  <!-- 3. Right Graphic: Trust Split Boundary Diagram -->
  <g transform="translate({badge_x}, {badge_y})" filter="url(#shadowC_{variant_name})">
    
    <!-- Outer Master Graphic Container -->
    <rect width="{badge_w}" height="{badge_h}" rx="{max(12, int(18*scale))}" fill="#031A22" stroke="#073B49" stroke-width="2"/>

    <!-- ZONE A: LOCAL AUTHORITY (Left ~56% of graphic) -->
    <rect x="{int(18*scale)}" y="{int(18*scale)}" width="{local_box_w}" height="{badge_h - int(36*scale)}" rx="{max(10, int(14*scale))}" fill="url(#localCardGradC_{variant_name})" stroke="#1F9D72" stroke-width="1.8"/>
    
    <!-- Zone Header -->
    <g transform="translate({int(30*scale)}, {int(44*scale)})">
      <circle cx="{int(8*scale)}" cy="{int(8*scale)}" r="{max(4.5, 6*scale)}" fill="#1F9D72"/>
      <text x="{int(22*scale)}" y="{int(12.5*scale)}" font-family="'Segoe UI', sans-serif" font-size="{local_hdr_fs}px" font-weight="800" fill="#F7F1E7" letter-spacing="1.2px">LOCAL AUTHORITY (DOMINANT)</text>
    </g>

    <!-- Node 1: Approved Files & Memory -->
    <g transform="translate({int(28*scale)}, {int(badge_h * 0.115)})">
      <rect width="{local_box_w - int(24*scale)}" height="{int(badge_h * 0.155)}" rx="{max(6, int(10*scale))}" fill="#04232C" stroke="#0E5C6E" stroke-width="1.2"/>
      <text x="{int(14*scale)}" y="{int(badge_h * 0.045)}" font-family="'Segoe UI', sans-serif" font-size="{local_title_fs}px" font-weight="700" fill="#5AD2D0">Approved Files &amp; Memory</text>
      <text x="{int(14*scale)}" y="{int(badge_h * 0.082)}" font-family="'Segoe UI', sans-serif" font-size="{local_desc_fs}px" fill="#C8E3E1">· Original documents never leave disk</text>
      <text x="{int(14*scale)}" y="{int(badge_h * 0.118)}" font-family="'Segoe UI', sans-serif" font-size="{local_desc_fs}px" fill="#C8E3E1">· Local index, hashes &amp; action ledgers</text>
    </g>

    <!-- Node 2: Policy & Privacy Gate -->
    <g transform="translate({int(28*scale)}, {int(badge_h * 0.29)})">
      <rect width="{local_box_w - int(24*scale)}" height="{int(badge_h * 0.155)}" rx="{max(6, int(10*scale))}" fill="#04232C" stroke="#FF6B4A" stroke-width="1.4"/>
      <text x="{int(14*scale)}" y="{int(badge_h * 0.045)}" font-family="'Segoe UI', sans-serif" font-size="{local_title_fs}px" font-weight="700" fill="#FF6B4A">Policy + Privacy Gate</text>
      <text x="{int(14*scale)}" y="{int(badge_h * 0.082)}" font-family="'Segoe UI', sans-serif" font-size="{local_desc_fs}px" fill="#C8E3E1">· Explicit scope &amp; pseudonymization</text>
      <text x="{int(14*scale)}" y="{int(badge_h * 0.118)}" font-family="'Segoe UI', sans-serif" font-size="{local_desc_fs}px" fill="#C8E3E1">· Fail closed: unapproved stays local</text>
    </g>

    <!-- Node 3: Local Evidence Verifier -->
    <g transform="translate({int(28*scale)}, {int(badge_h * 0.465)})">
      <rect width="{local_box_w - int(24*scale)}" height="{int(badge_h * 0.155)}" rx="{max(6, int(10*scale))}" fill="#04232C" stroke="#1F9D72" stroke-width="1.4"/>
      <text x="{int(14*scale)}" y="{int(badge_h * 0.045)}" font-family="'Segoe UI', sans-serif" font-size="{local_title_fs}px" font-weight="700" fill="#1F9D72">Evidence Verifier</text>
      <text x="{int(14*scale)}" y="{int(badge_h * 0.082)}" font-family="'Segoe UI', sans-serif" font-size="{local_desc_fs}px" fill="#C8E3E1">· Checks quotes against local text</text>
      <text x="{int(14*scale)}" y="{int(badge_h * 0.118)}" font-family="'Segoe UI', sans-serif" font-size="{local_desc_fs}px" fill="#C8E3E1">· Verifies source IDs &amp; schema before commit</text>
    </g>

    <!-- Local Summary Guarantee Bar -->
    <g transform="translate({int(28*scale)}, {badge_h - max(36, int(54*scale))})">
      <rect width="{local_box_w - int(24*scale)}" height="{max(28, int(38*scale))}" rx="{max(6, int(8*scale))}" fill="#073B49" stroke="#1F9D72" stroke-width="1" stroke-dasharray="4 3"/>
      <text x="{int((local_box_w - 24*scale)/2)}" y="{max(19, int(24*scale))}" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="{guar_fs}px" font-weight="700" fill="#5AD2D0">NO ORIGINAL FILES OR HOST PATHS</text>
    </g>

    <!-- TRUST BOUNDARY DIVIDER -->
    <g transform="translate({divider_x}, {int(24*scale)})">
      <line x1="0" y1="0" x2="0" y2="{badge_h - int(48*scale)}" stroke="#5AD2D0" stroke-width="2" stroke-dasharray="6 4" filter="url(#glowCyanC_{variant_name})"/>
    </g>

    <!-- ZONE B: BOUNDED REASONING (Right ~34% of graphic) -->
    <g transform="translate({cloud_box_x}, {int(18*scale)})">
      <rect width="{cloud_box_w}" height="{badge_h - int(36*scale)}" rx="{max(10, int(14*scale))}" fill="url(#cloudCardGradC_{variant_name})" stroke="#818CF8" stroke-width="1.5"/>
      
      <!-- Zone Header -->
      <g transform="translate({int(14*scale)}, {int(44*scale)})">
        <circle cx="{int(7*scale)}" cy="{int(7*scale)}" r="{max(4, 5.5*scale)}" fill="#818CF8"/>
        <text x="{int(18*scale)}" y="{int(11.5*scale)}" font-family="'Segoe UI', sans-serif" font-size="{cloud_hdr_fs}px" font-weight="800" fill="#C7D2FE" letter-spacing="0.8px">BOUNDED ZONE</text>
      </g>

      <!-- Cloud Reasoning Box (4 Proven Items) -->
      <g transform="translate({int(14*scale)}, {int(badge_h * 0.115)})">
        <rect width="{cloud_box_w - int(28*scale)}" height="{int(badge_h * 0.40)}" rx="{max(6, int(10*scale))}" fill="#0A0F1D" stroke="#6366F1" stroke-width="1.4"/>
        <text x="{int(12*scale)}" y="{int(badge_h * 0.045)}" font-family="'Segoe UI', sans-serif" font-size="{cloud_model_fs}px" font-weight="700" fill="#A5B4FC">NVIDIA Nemotron</text>
        <text x="{int(12*scale)}" y="{int(badge_h * 0.078)}" font-family="'Segoe UI', sans-serif" font-size="{cloud_sub_fs}px" font-weight="600" fill="#818CF8">on Nebius</text>
        
        <line x1="{int(12*scale)}" y1="{int(badge_h * 0.098)}" x2="{cloud_box_w - int(40*scale)}" y2="{int(badge_h * 0.098)}" stroke="#334155" stroke-width="1"/>

        <text x="{int(12*scale)}" y="{int(badge_h * 0.145)}" font-family="'Segoe UI', sans-serif" font-size="{cloud_item_fs}px" fill="#94A3B8">· Optional reasoning</text>
        <text x="{int(12*scale)}" y="{int(badge_h * 0.185)}" font-family="'Segoe UI', sans-serif" font-size="{cloud_item_fs}px" fill="#94A3B8">· Selected context</text>
        <text x="{int(12*scale)}" y="{int(badge_h * 0.225)}" font-family="'Segoe UI', sans-serif" font-size="{cloud_item_fs}px" fill="#94A3B8">· Pseudonymized</text>
        <text x="{int(12*scale)}" y="{int(badge_h * 0.265)}" font-family="'Segoe UI', sans-serif" font-size="{cloud_item_fs}px" fill="#94A3B8">· Bounded budget</text>
      </g>

      <!-- Return Path Box -->
      <g transform="translate({int(14*scale)}, {badge_h - max(72, int(96*scale))})">
        <rect width="{cloud_box_w - int(28*scale)}" height="{max(48, int(64*scale))}" rx="{max(6, int(8*scale))}" fill="#0A0F1D" stroke="#1F9D72" stroke-width="1.2" stroke-dasharray="3 3"/>
        <text x="{int((cloud_box_w - 28*scale)/2)}" y="{max(20, int(27*scale))}" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="{ret_hdr_fs}px" font-weight="700" fill="#1F9D72">RETURN PATH ONLY</text>
        <text x="{int((cloud_box_w - 28*scale)/2)}" y="{max(36, int(46*scale))}" text-anchor="middle" font-family="'Segoe UI', sans-serif" font-size="{ret_sub_fs}px" font-weight="700" fill="#5AD2D0">TO LOCAL VERIFIER</text>
      </g>
    </g>

  </g>
</svg>"""
    return svg

def render_svg_to_png(svg_path, png_path, width, height):
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    edge_x86_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    edge_x64_path = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"

    if os.path.exists(chrome_path):
        browser = chrome_path
    elif os.path.exists(edge_x86_path):
        browser = edge_x86_path
    elif os.path.exists(edge_x64_path):
        browser = edge_x64_path
    else:
        raise RuntimeError(
            "No supported browser found for host PNG rendering. "
            "Google Chrome or Microsoft Edge is required to render SVG assets to PNG."
        )

    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--allow-file-access-from-files",
        "--force-device-scale-factor=1",
        f"--window-size={width},{height}",
        f"--screenshot={os.path.abspath(png_path)}",
        os.path.abspath(svg_path)
    ]
    subprocess.run(cmd, check=True)

def main():
    variants = [
        ("banner", 1600, 900),
        ("thumbnail", 1280, 720),
        ("social", 1200, 630)
    ]

    concepts = [
        ("trust-voyage", get_concept_a_svg, "Concept A: Oceanic Depth & Calm Negative Space"),
        ("evidence-ledger", get_concept_b_svg, "Concept B: Light Editorial Evidence Board & Traceability"),
        ("bounded-reasoning", get_concept_c_svg, "Concept C: Dark Split-Boundary Campaign Graphic")
    ]

    manifest = {
        "title": "NemoFold Jury Design Set",
        "description": "Visual asset suite for NemoFold evidence-first document agent.",
        "tagline": "Your files. Your rules. Your agent.",
        "brand_direction": {
            "palette": {
                "deep_teal_dark": "#073B49",
                "deep_teal_light": "#0B4A59",
                "warm_ivory": "#F7F1E7",
                "coral_accent": "#FF6B4A",
                "cyan_accent": "#5AD2D0",
                "emerald_verification": "#1F9D72",
                "slate_primary": "#0F172A",
                "slate_secondary": "#334155"
            },
            "typography": {
                "primary": "Segoe UI, -apple-system, sans-serif",
                "editorial_serif": "Georgia, serif"
            },
            "status_invariants": [
                "Local core ready",
                "Live cloud proof open",
                "Cloud proof: pending"
            ]
        },
        "sources": [
            {
                "file": "sources/nemofold-console-reference.png",
                "format": "PNG",
                "description": "Current product console and brand direction reference"
            },
            {
                "file": "sources/nemofold-trust-boundary-reference.svg",
                "format": "SVG",
                "description": "Accessible trust-boundary diagram and palette reference"
            },
            {
                "file": "sources/trust-voyage-background.png",
                "format": "PNG",
                "description": "Text-free hero bitmap background for Concept A (Trust Voyage)"
            }
        ],
        "concepts": []
    }

    print("Generating SVGs and rendering PNGs...")

    for c_id, svg_fn, c_desc in concepts:
        c_entry = {
            "id": c_id,
            "title": c_desc,
            "deliverables": []
        }
        for v_name, w, h in variants:
            svg_filename = f"{c_id}-{v_name}.svg"
            png_filename = f"{c_id}-{v_name}.png"
            svg_path = os.path.join(BASE_DIR, svg_filename)
            png_path = os.path.join(BASE_DIR, png_filename)

            # Generate SVG content
            svg_content = svg_fn(w, h, v_name)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)

            # Render PNG
            render_svg_to_png(svg_path, png_path, w, h)

            # Verify with Pillow
            with Image.open(png_path) as im:
                actual_w, actual_h = im.size
                mode = im.mode

            print(f"Generated {png_filename}: {actual_w}x{actual_h} ({mode})")

            c_entry["deliverables"].append({
                "variant": v_name,
                "svg": {
                    "file": svg_filename,
                    "format": "SVG",
                    "viewBox": f"0 0 {w} {h}"
                },
                "png": {
                    "file": png_filename,
                    "format": "PNG",
                    "width": actual_w,
                    "height": actual_h,
                    "mode": mode
                },
                "target_dimensions": f"{w}x{h}",
                "actual_dimensions": f"{actual_w}x{actual_h}",
                "status": "VERIFIED" if (actual_w == w and actual_h == h) else "DIMENSION_MISMATCH"
            })
        manifest["concepts"].append(c_entry)

    # Write manifest.json
    manifest_path = os.path.join(BASE_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote {manifest_path}")

if __name__ == "__main__":
    main()
