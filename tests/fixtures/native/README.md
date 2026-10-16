# Synthetic native controls

TechnicalContact_Control создан 2026-10-17 для native validation kit.
Это synthetic source, не официальный KiCad library footprint. Unnamed F.Paste
pad становится __TECH_1 без copper/hole; contact1 использует B.Cu/B.Mask, no paste.
Margins .05/0/0 выбраны явно. Проверять netlist exposure carrier, paste и contact
semantics нужно в FreePCB2/Gerber: native flags остаются false.
