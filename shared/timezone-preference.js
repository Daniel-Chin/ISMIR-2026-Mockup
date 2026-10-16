'use strict';

(function () {
  // Not persisted: like miniconf, every visit starts from the system time zone.
  const FALLBACK_ZONE = window.ISMIRSite.timeZone;


  // Search metadata is generated from the IANA tzdb country/zone tables.
  // The actual selected value always remains an IANA time-zone identifier.
  const IANA_ZONE_SEARCH_META = {"Europe/Andorra":{"codes":["AD"],"countries":["Andorra"]},"Asia/Dubai":{"codes":["AE"],"countries":["United Arab Emirates"]},"Asia/Kabul":{"codes":["AF"],"countries":["Afghanistan"]},"America/Antigua":{"codes":["AG"],"countries":["Antigua & Barbuda"]},"America/Anguilla":{"codes":["AI"],"countries":["Anguilla"]},"Europe/Tirane":{"codes":["AL"],"countries":["Albania"]},"Asia/Yerevan":{"codes":["AM"],"countries":["Armenia"]},"Africa/Luanda":{"codes":["AO"],"countries":["Angola"]},"Antarctica/McMurdo":{"codes":["AQ"],"countries":["Antarctica"],"comments":["New Zealand time - McMurdo, South Pole"]},"Antarctica/Casey":{"codes":["AQ"],"countries":["Antarctica"],"comments":["Casey"]},"Antarctica/Davis":{"codes":["AQ"],"countries":["Antarctica"],"comments":["Davis"]},"Antarctica/DumontDUrville":{"codes":["AQ"],"countries":["Antarctica"],"comments":["Dumont-d'Urville"]},"Antarctica/Mawson":{"codes":["AQ"],"countries":["Antarctica"],"comments":["Mawson"]},"Antarctica/Palmer":{"codes":["AQ"],"countries":["Antarctica"],"comments":["Palmer"]},"Antarctica/Rothera":{"codes":["AQ"],"countries":["Antarctica"],"comments":["Rothera"]},"Antarctica/Syowa":{"codes":["AQ"],"countries":["Antarctica"],"comments":["Syowa"]},"Antarctica/Troll":{"codes":["AQ"],"countries":["Antarctica"],"comments":["Troll"]},"Antarctica/Vostok":{"codes":["AQ"],"countries":["Antarctica"],"comments":["Vostok"]},"America/Argentina/Buenos_Aires":{"codes":["AR"],"countries":["Argentina"],"comments":["Buenos Aires (BA, CF)"]},"America/Argentina/Cordoba":{"codes":["AR"],"countries":["Argentina"],"comments":["Argentina (most areas: CB, CC, CN, ER, FM, MN, SE, SF)"]},"America/Argentina/Salta":{"codes":["AR"],"countries":["Argentina"],"comments":["Salta (SA, LP, NQ, RN)"]},"America/Argentina/Jujuy":{"codes":["AR"],"countries":["Argentina"],"comments":["Jujuy (JY)"]},"America/Argentina/Tucuman":{"codes":["AR"],"countries":["Argentina"],"comments":["Tucuman (TM)"]},"America/Argentina/Catamarca":{"codes":["AR"],"countries":["Argentina"],"comments":["Catamarca (CT), Chubut (CH)"]},"America/Argentina/La_Rioja":{"codes":["AR"],"countries":["Argentina"],"comments":["La Rioja (LR)"]},"America/Argentina/San_Juan":{"codes":["AR"],"countries":["Argentina"],"comments":["San Juan (SJ)"]},"America/Argentina/Mendoza":{"codes":["AR"],"countries":["Argentina"],"comments":["Mendoza (MZ)"]},"America/Argentina/San_Luis":{"codes":["AR"],"countries":["Argentina"],"comments":["San Luis (SL)"]},"America/Argentina/Rio_Gallegos":{"codes":["AR"],"countries":["Argentina"],"comments":["Santa Cruz (SC)"]},"America/Argentina/Ushuaia":{"codes":["AR"],"countries":["Argentina"],"comments":["Tierra del Fuego (TF)"]},"Pacific/Pago_Pago":{"codes":["AS"],"countries":["Samoa (American)"]},"Europe/Vienna":{"codes":["AT"],"countries":["Austria"]},"Australia/Lord_Howe":{"codes":["AU"],"countries":["Australia"],"comments":["Lord Howe Island"]},"Antarctica/Macquarie":{"codes":["AU"],"countries":["Australia"],"comments":["Macquarie Island"]},"Australia/Hobart":{"codes":["AU"],"countries":["Australia"],"comments":["Tasmania"]},"Australia/Melbourne":{"codes":["AU"],"countries":["Australia"],"comments":["Victoria"]},"Australia/Sydney":{"codes":["AU"],"countries":["Australia"],"comments":["New South Wales (most areas)"]},"Australia/Broken_Hill":{"codes":["AU"],"countries":["Australia"],"comments":["New South Wales (Yancowinna)"]},"Australia/Brisbane":{"codes":["AU"],"countries":["Australia"],"comments":["Queensland (most areas)"]},"Australia/Lindeman":{"codes":["AU"],"countries":["Australia"],"comments":["Queensland (Whitsunday Islands)"]},"Australia/Adelaide":{"codes":["AU"],"countries":["Australia"],"comments":["South Australia"]},"Australia/Darwin":{"codes":["AU"],"countries":["Australia"],"comments":["Northern Territory"]},"Australia/Perth":{"codes":["AU"],"countries":["Australia"],"comments":["Western Australia (most areas)"]},"Australia/Eucla":{"codes":["AU"],"countries":["Australia"],"comments":["Western Australia (Eucla)"]},"America/Aruba":{"codes":["AW"],"countries":["Aruba"]},"Europe/Mariehamn":{"codes":["AX"],"countries":["Åland Islands"]},"Asia/Baku":{"codes":["AZ"],"countries":["Azerbaijan"]},"Europe/Sarajevo":{"codes":["BA"],"countries":["Bosnia & Herzegovina"]},"America/Barbados":{"codes":["BB"],"countries":["Barbados"]},"Asia/Dhaka":{"codes":["BD"],"countries":["Bangladesh"]},"Europe/Brussels":{"codes":["BE"],"countries":["Belgium"]},"Africa/Ouagadougou":{"codes":["BF"],"countries":["Burkina Faso"]},"Europe/Sofia":{"codes":["BG"],"countries":["Bulgaria"]},"Asia/Bahrain":{"codes":["BH"],"countries":["Bahrain"]},"Africa/Bujumbura":{"codes":["BI"],"countries":["Burundi"]},"Africa/Porto-Novo":{"codes":["BJ"],"countries":["Benin"]},"America/St_Barthelemy":{"codes":["BL"],"countries":["St Barthelemy"]},"Atlantic/Bermuda":{"codes":["BM"],"countries":["Bermuda"]},"Asia/Brunei":{"codes":["BN"],"countries":["Brunei"]},"America/La_Paz":{"codes":["BO"],"countries":["Bolivia"]},"America/Kralendijk":{"codes":["BQ"],"countries":["Caribbean NL"]},"America/Noronha":{"codes":["BR"],"countries":["Brazil"],"comments":["Atlantic islands"]},"America/Belem":{"codes":["BR"],"countries":["Brazil"],"comments":["Para (east), Amapa"]},"America/Fortaleza":{"codes":["BR"],"countries":["Brazil"],"comments":["Brazil (northeast: MA, PI, CE, RN, PB)"]},"America/Recife":{"codes":["BR"],"countries":["Brazil"],"comments":["Pernambuco"]},"America/Araguaina":{"codes":["BR"],"countries":["Brazil"],"comments":["Tocantins"]},"America/Maceio":{"codes":["BR"],"countries":["Brazil"],"comments":["Alagoas, Sergipe"]},"America/Bahia":{"codes":["BR"],"countries":["Brazil"],"comments":["Bahia"]},"America/Sao_Paulo":{"codes":["BR"],"countries":["Brazil"],"comments":["Brazil (southeast: GO, DF, MG, ES, RJ, SP, PR, SC, RS)"]},"America/Campo_Grande":{"codes":["BR"],"countries":["Brazil"],"comments":["Mato Grosso do Sul"]},"America/Cuiaba":{"codes":["BR"],"countries":["Brazil"],"comments":["Mato Grosso"]},"America/Santarem":{"codes":["BR"],"countries":["Brazil"],"comments":["Para (west)"]},"America/Porto_Velho":{"codes":["BR"],"countries":["Brazil"],"comments":["Rondonia"]},"America/Boa_Vista":{"codes":["BR"],"countries":["Brazil"],"comments":["Roraima"]},"America/Manaus":{"codes":["BR"],"countries":["Brazil"],"comments":["Amazonas (east)"]},"America/Eirunepe":{"codes":["BR"],"countries":["Brazil"],"comments":["Amazonas (west)"]},"America/Rio_Branco":{"codes":["BR"],"countries":["Brazil"],"comments":["Acre"]},"America/Nassau":{"codes":["BS"],"countries":["Bahamas"]},"Asia/Thimphu":{"codes":["BT"],"countries":["Bhutan"]},"Africa/Gaborone":{"codes":["BW"],"countries":["Botswana"]},"Europe/Minsk":{"codes":["BY"],"countries":["Belarus"]},"America/Belize":{"codes":["BZ"],"countries":["Belize"]},"America/St_Johns":{"codes":["CA"],"countries":["Canada"],"comments":["Newfoundland, Labrador (SE)"]},"America/Halifax":{"codes":["CA"],"countries":["Canada"],"comments":["Atlantic - NS (most areas), PE"]},"America/Glace_Bay":{"codes":["CA"],"countries":["Canada"],"comments":["Atlantic - NS (Cape Breton)"]},"America/Moncton":{"codes":["CA"],"countries":["Canada"],"comments":["Atlantic - New Brunswick"]},"America/Goose_Bay":{"codes":["CA"],"countries":["Canada"],"comments":["Atlantic - Labrador (most areas)"]},"America/Blanc-Sablon":{"codes":["CA"],"countries":["Canada"],"comments":["AST - QC (Lower North Shore)"]},"America/Toronto":{"codes":["CA"],"countries":["Canada"],"comments":["Eastern - ON & QC (most areas)"]},"America/Iqaluit":{"codes":["CA"],"countries":["Canada"],"comments":["Eastern - NU (most areas)"]},"America/Atikokan":{"codes":["CA"],"countries":["Canada"],"comments":["EST - ON (Atikokan), NU (Coral H)"]},"America/Winnipeg":{"codes":["CA"],"countries":["Canada"],"comments":["Central - ON (west), Manitoba"]},"America/Resolute":{"codes":["CA"],"countries":["Canada"],"comments":["Central - NU (Resolute)"]},"America/Rankin_Inlet":{"codes":["CA"],"countries":["Canada"],"comments":["Central - NU (central)"]},"America/Regina":{"codes":["CA"],"countries":["Canada"],"comments":["CST - SK (most areas)"]},"America/Swift_Current":{"codes":["CA"],"countries":["Canada"],"comments":["CST - SK (midwest)"]},"America/Edmonton":{"codes":["CA"],"countries":["Canada"],"comments":["CST - AB, BC(E), NT(E), SK(W)"]},"America/Cambridge_Bay":{"codes":["CA"],"countries":["Canada"],"comments":["Mountain - NU (west)"]},"America/Inuvik":{"codes":["CA"],"countries":["Canada"],"comments":["Mountain - NT (west)"]},"America/Vancouver":{"codes":["CA"],"countries":["Canada"],"comments":["MST - BC (most areas)"]},"America/Creston":{"codes":["CA"],"countries":["Canada"],"comments":["MST - BC (Creston)"]},"America/Dawson_Creek":{"codes":["CA"],"countries":["Canada"],"comments":["MST - BC (Dawson Cr, Ft St John)"]},"America/Fort_Nelson":{"codes":["CA"],"countries":["Canada"],"comments":["MST - BC (Ft Nelson)"]},"America/Whitehorse":{"codes":["CA"],"countries":["Canada"],"comments":["MST - Yukon (east)"]},"America/Dawson":{"codes":["CA"],"countries":["Canada"],"comments":["MST - Yukon (west)"]},"Indian/Cocos":{"codes":["CC"],"countries":["Cocos (Keeling) Islands"]},"Africa/Kinshasa":{"codes":["CD"],"countries":["Congo (Dem. Rep.)"],"comments":["Dem. Rep. of Congo (west)"]},"Africa/Lubumbashi":{"codes":["CD"],"countries":["Congo (Dem. Rep.)"],"comments":["Dem. Rep. of Congo (east)"]},"Africa/Bangui":{"codes":["CF"],"countries":["Central African Rep."]},"Africa/Brazzaville":{"codes":["CG"],"countries":["Congo (Rep.)"]},"Europe/Zurich":{"codes":["CH"],"countries":["Switzerland"]},"Africa/Abidjan":{"codes":["CI"],"countries":["Côte d’Ivoire"]},"Pacific/Rarotonga":{"codes":["CK"],"countries":["Cook Islands"]},"America/Santiago":{"codes":["CL"],"countries":["Chile"],"comments":["most of Chile"]},"America/Coyhaique":{"codes":["CL"],"countries":["Chile"],"comments":["Aysen Region"]},"America/Punta_Arenas":{"codes":["CL"],"countries":["Chile"],"comments":["Magallanes Region"]},"Pacific/Easter":{"codes":["CL"],"countries":["Chile"],"comments":["Easter Island"]},"Africa/Douala":{"codes":["CM"],"countries":["Cameroon"]},"Asia/Shanghai":{"codes":["CN"],"countries":["China"],"comments":["Beijing Time"]},"Asia/Urumqi":{"codes":["CN"],"countries":["China"],"comments":["Xinjiang Time"]},"America/Bogota":{"codes":["CO"],"countries":["Colombia"]},"America/Costa_Rica":{"codes":["CR"],"countries":["Costa Rica"]},"America/Havana":{"codes":["CU"],"countries":["Cuba"]},"Atlantic/Cape_Verde":{"codes":["CV"],"countries":["Cape Verde"]},"America/Curacao":{"codes":["CW"],"countries":["Curaçao"]},"Indian/Christmas":{"codes":["CX"],"countries":["Christmas Island"]},"Asia/Nicosia":{"codes":["CY"],"countries":["Cyprus"],"comments":["most of Cyprus"]},"Asia/Famagusta":{"codes":["CY"],"countries":["Cyprus"],"comments":["Northern Cyprus"]},"Europe/Prague":{"codes":["CZ"],"countries":["Czech Republic"]},"Europe/Berlin":{"codes":["DE"],"countries":["Germany"],"comments":["most of Germany"]},"Europe/Busingen":{"codes":["DE"],"countries":["Germany"],"comments":["Busingen"]},"Africa/Djibouti":{"codes":["DJ"],"countries":["Djibouti"]},"Europe/Copenhagen":{"codes":["DK"],"countries":["Denmark"]},"America/Dominica":{"codes":["DM"],"countries":["Dominica"]},"America/Santo_Domingo":{"codes":["DO"],"countries":["Dominican Republic"]},"Africa/Algiers":{"codes":["DZ"],"countries":["Algeria"]},"America/Guayaquil":{"codes":["EC"],"countries":["Ecuador"],"comments":["Ecuador (mainland)"]},"Pacific/Galapagos":{"codes":["EC"],"countries":["Ecuador"],"comments":["Galapagos Islands"]},"Europe/Tallinn":{"codes":["EE"],"countries":["Estonia"]},"Africa/Cairo":{"codes":["EG"],"countries":["Egypt"]},"Africa/El_Aaiun":{"codes":["EH"],"countries":["Western Sahara"]},"Africa/Asmara":{"codes":["ER"],"countries":["Eritrea"]},"Europe/Madrid":{"codes":["ES"],"countries":["Spain"],"comments":["Spain (mainland)"]},"Africa/Ceuta":{"codes":["ES"],"countries":["Spain"],"comments":["Ceuta, Melilla"]},"Atlantic/Canary":{"codes":["ES"],"countries":["Spain"],"comments":["Canary Islands"]},"Africa/Addis_Ababa":{"codes":["ET"],"countries":["Ethiopia"]},"Europe/Helsinki":{"codes":["FI"],"countries":["Finland"]},"Pacific/Fiji":{"codes":["FJ"],"countries":["Fiji"]},"Atlantic/Stanley":{"codes":["FK"],"countries":["Falkland Islands"]},"Pacific/Chuuk":{"codes":["FM"],"countries":["Micronesia"],"comments":["Chuuk/Truk, Yap"]},"Pacific/Pohnpei":{"codes":["FM"],"countries":["Micronesia"],"comments":["Pohnpei/Ponape"]},"Pacific/Kosrae":{"codes":["FM"],"countries":["Micronesia"],"comments":["Kosrae"]},"Atlantic/Faroe":{"codes":["FO"],"countries":["Faroe Islands"]},"Europe/Paris":{"codes":["FR"],"countries":["France"]},"Africa/Libreville":{"codes":["GA"],"countries":["Gabon"]},"Europe/London":{"codes":["GB"],"countries":["Britain (UK)"]},"America/Grenada":{"codes":["GD"],"countries":["Grenada"]},"Asia/Tbilisi":{"codes":["GE"],"countries":["Georgia"]},"America/Cayenne":{"codes":["GF"],"countries":["French Guiana"]},"Europe/Guernsey":{"codes":["GG"],"countries":["Guernsey"]},"Africa/Accra":{"codes":["GH"],"countries":["Ghana"]},"Europe/Gibraltar":{"codes":["GI"],"countries":["Gibraltar"]},"America/Nuuk":{"codes":["GL"],"countries":["Greenland"],"comments":["most of Greenland"]},"America/Danmarkshavn":{"codes":["GL"],"countries":["Greenland"],"comments":["National Park (east coast)"]},"America/Scoresbysund":{"codes":["GL"],"countries":["Greenland"],"comments":["Scoresbysund/Ittoqqortoormiit"]},"America/Thule":{"codes":["GL"],"countries":["Greenland"],"comments":["Thule/Pituffik"]},"Africa/Banjul":{"codes":["GM"],"countries":["Gambia"]},"Africa/Conakry":{"codes":["GN"],"countries":["Guinea"]},"America/Guadeloupe":{"codes":["GP"],"countries":["Guadeloupe"]},"Africa/Malabo":{"codes":["GQ"],"countries":["Equatorial Guinea"]},"Europe/Athens":{"codes":["GR"],"countries":["Greece"]},"Atlantic/South_Georgia":{"codes":["GS"],"countries":["South Georgia & the South Sandwich Islands"]},"America/Guatemala":{"codes":["GT"],"countries":["Guatemala"]},"Pacific/Guam":{"codes":["GU"],"countries":["Guam"]},"Africa/Bissau":{"codes":["GW"],"countries":["Guinea-Bissau"]},"America/Guyana":{"codes":["GY"],"countries":["Guyana"]},"Asia/Hong_Kong":{"codes":["HK"],"countries":["Hong Kong"]},"America/Tegucigalpa":{"codes":["HN"],"countries":["Honduras"]},"Europe/Zagreb":{"codes":["HR"],"countries":["Croatia"]},"America/Port-au-Prince":{"codes":["HT"],"countries":["Haiti"]},"Europe/Budapest":{"codes":["HU"],"countries":["Hungary"]},"Asia/Jakarta":{"codes":["ID"],"countries":["Indonesia"],"comments":["Java, Sumatra"]},"Asia/Pontianak":{"codes":["ID"],"countries":["Indonesia"],"comments":["Borneo (west, central)"]},"Asia/Makassar":{"codes":["ID"],"countries":["Indonesia"],"comments":["Borneo (east, south), Sulawesi/Celebes, Bali, Nusa Tengarra, Timor (west)"]},"Asia/Jayapura":{"codes":["ID"],"countries":["Indonesia"],"comments":["New Guinea (West Papua / Irian Jaya), Malukus/Moluccas"]},"Europe/Dublin":{"codes":["IE"],"countries":["Ireland"]},"Asia/Jerusalem":{"codes":["IL"],"countries":["Israel"]},"Europe/Isle_of_Man":{"codes":["IM"],"countries":["Isle of Man"]},"Asia/Kolkata":{"codes":["IN"],"countries":["India"]},"Indian/Chagos":{"codes":["IO"],"countries":["British Indian Ocean Territory"]},"Asia/Baghdad":{"codes":["IQ"],"countries":["Iraq"]},"Asia/Tehran":{"codes":["IR"],"countries":["Iran"]},"Atlantic/Reykjavik":{"codes":["IS"],"countries":["Iceland"]},"Europe/Rome":{"codes":["IT"],"countries":["Italy"]},"Europe/Jersey":{"codes":["JE"],"countries":["Jersey"]},"America/Jamaica":{"codes":["JM"],"countries":["Jamaica"]},"Asia/Amman":{"codes":["JO"],"countries":["Jordan"]},"Asia/Tokyo":{"codes":["JP"],"countries":["Japan"]},"Africa/Nairobi":{"codes":["KE"],"countries":["Kenya"]},"Asia/Bishkek":{"codes":["KG"],"countries":["Kyrgyzstan"]},"Asia/Phnom_Penh":{"codes":["KH"],"countries":["Cambodia"]},"Pacific/Tarawa":{"codes":["KI"],"countries":["Kiribati"],"comments":["Gilbert Islands"]},"Pacific/Kanton":{"codes":["KI"],"countries":["Kiribati"],"comments":["Phoenix Islands"]},"Pacific/Kiritimati":{"codes":["KI"],"countries":["Kiribati"],"comments":["Line Islands"]},"Indian/Comoro":{"codes":["KM"],"countries":["Comoros"]},"America/St_Kitts":{"codes":["KN"],"countries":["St Kitts & Nevis"]},"Asia/Pyongyang":{"codes":["KP"],"countries":["Korea (North)"]},"Asia/Seoul":{"codes":["KR"],"countries":["Korea (South)"]},"Asia/Kuwait":{"codes":["KW"],"countries":["Kuwait"]},"America/Cayman":{"codes":["KY"],"countries":["Cayman Islands"]},"Asia/Almaty":{"codes":["KZ"],"countries":["Kazakhstan"],"comments":["most of Kazakhstan"]},"Asia/Qyzylorda":{"codes":["KZ"],"countries":["Kazakhstan"],"comments":["Qyzylorda/Kyzylorda/Kzyl-Orda"]},"Asia/Qostanay":{"codes":["KZ"],"countries":["Kazakhstan"],"comments":["Qostanay/Kostanay/Kustanay"]},"Asia/Aqtobe":{"codes":["KZ"],"countries":["Kazakhstan"],"comments":["Aqtobe/Aktobe"]},"Asia/Aqtau":{"codes":["KZ"],"countries":["Kazakhstan"],"comments":["Mangghystau/Mankistau"]},"Asia/Atyrau":{"codes":["KZ"],"countries":["Kazakhstan"],"comments":["Atyrau/Atirau/Gur'yev"]},"Asia/Oral":{"codes":["KZ"],"countries":["Kazakhstan"],"comments":["West Kazakhstan"]},"Asia/Vientiane":{"codes":["LA"],"countries":["Laos"]},"Asia/Beirut":{"codes":["LB"],"countries":["Lebanon"]},"America/St_Lucia":{"codes":["LC"],"countries":["St Lucia"]},"Europe/Vaduz":{"codes":["LI"],"countries":["Liechtenstein"]},"Asia/Colombo":{"codes":["LK"],"countries":["Sri Lanka"]},"Africa/Monrovia":{"codes":["LR"],"countries":["Liberia"]},"Africa/Maseru":{"codes":["LS"],"countries":["Lesotho"]},"Europe/Vilnius":{"codes":["LT"],"countries":["Lithuania"]},"Europe/Luxembourg":{"codes":["LU"],"countries":["Luxembourg"]},"Europe/Riga":{"codes":["LV"],"countries":["Latvia"]},"Africa/Tripoli":{"codes":["LY"],"countries":["Libya"]},"Africa/Casablanca":{"codes":["MA"],"countries":["Morocco"]},"Europe/Monaco":{"codes":["MC"],"countries":["Monaco"]},"Europe/Chisinau":{"codes":["MD"],"countries":["Moldova"]},"Europe/Podgorica":{"codes":["ME"],"countries":["Montenegro"]},"America/Marigot":{"codes":["MF"],"countries":["St Martin (French)"]},"Indian/Antananarivo":{"codes":["MG"],"countries":["Madagascar"]},"Pacific/Majuro":{"codes":["MH"],"countries":["Marshall Islands"],"comments":["most of Marshall Islands"]},"Pacific/Kwajalein":{"codes":["MH"],"countries":["Marshall Islands"],"comments":["Kwajalein"]},"Europe/Skopje":{"codes":["MK"],"countries":["North Macedonia"]},"Africa/Bamako":{"codes":["ML"],"countries":["Mali"]},"Asia/Yangon":{"codes":["MM"],"countries":["Myanmar (Burma)"]},"Asia/Ulaanbaatar":{"codes":["MN"],"countries":["Mongolia"],"comments":["most of Mongolia"]},"Asia/Hovd":{"codes":["MN"],"countries":["Mongolia"],"comments":["Bayan-Olgii, Hovd, Uvs"]},"Asia/Macau":{"codes":["MO"],"countries":["Macau"]},"Pacific/Saipan":{"codes":["MP"],"countries":["Northern Mariana Islands"]},"America/Martinique":{"codes":["MQ"],"countries":["Martinique"]},"Africa/Nouakchott":{"codes":["MR"],"countries":["Mauritania"]},"America/Montserrat":{"codes":["MS"],"countries":["Montserrat"]},"Europe/Malta":{"codes":["MT"],"countries":["Malta"]},"Indian/Mauritius":{"codes":["MU"],"countries":["Mauritius"]},"Indian/Maldives":{"codes":["MV"],"countries":["Maldives"]},"Africa/Blantyre":{"codes":["MW"],"countries":["Malawi"]},"America/Mexico_City":{"codes":["MX"],"countries":["Mexico"],"comments":["Central Mexico"]},"America/Cancun":{"codes":["MX"],"countries":["Mexico"],"comments":["Quintana Roo"]},"America/Merida":{"codes":["MX"],"countries":["Mexico"],"comments":["Campeche, Yucatan"]},"America/Monterrey":{"codes":["MX"],"countries":["Mexico"],"comments":["Durango; Coahuila, Nuevo Leon, Tamaulipas (most areas)"]},"America/Matamoros":{"codes":["MX"],"countries":["Mexico"],"comments":["Coahuila, Nuevo Leon, Tamaulipas (US border)"]},"America/Chihuahua":{"codes":["MX"],"countries":["Mexico"],"comments":["Chihuahua (most areas)"]},"America/Ciudad_Juarez":{"codes":["MX"],"countries":["Mexico"],"comments":["Chihuahua (US border - west)"]},"America/Ojinaga":{"codes":["MX"],"countries":["Mexico"],"comments":["Chihuahua (US border - east)"]},"America/Mazatlan":{"codes":["MX"],"countries":["Mexico"],"comments":["Baja California Sur, Nayarit (most areas), Sinaloa"]},"America/Bahia_Banderas":{"codes":["MX"],"countries":["Mexico"],"comments":["Bahia de Banderas"]},"America/Hermosillo":{"codes":["MX"],"countries":["Mexico"],"comments":["Sonora"]},"America/Tijuana":{"codes":["MX"],"countries":["Mexico"],"comments":["Baja California"]},"Asia/Kuala_Lumpur":{"codes":["MY"],"countries":["Malaysia"],"comments":["Malaysia (peninsula)"]},"Asia/Kuching":{"codes":["MY"],"countries":["Malaysia"],"comments":["Sabah, Sarawak"]},"Africa/Maputo":{"codes":["MZ"],"countries":["Mozambique"]},"Africa/Windhoek":{"codes":["NA"],"countries":["Namibia"]},"Pacific/Noumea":{"codes":["NC"],"countries":["New Caledonia"]},"Africa/Niamey":{"codes":["NE"],"countries":["Niger"]},"Pacific/Norfolk":{"codes":["NF"],"countries":["Norfolk Island"]},"Africa/Lagos":{"codes":["NG"],"countries":["Nigeria"]},"America/Managua":{"codes":["NI"],"countries":["Nicaragua"]},"Europe/Amsterdam":{"codes":["NL"],"countries":["Netherlands"]},"Europe/Oslo":{"codes":["NO"],"countries":["Norway"]},"Asia/Kathmandu":{"codes":["NP"],"countries":["Nepal"]},"Pacific/Nauru":{"codes":["NR"],"countries":["Nauru"]},"Pacific/Niue":{"codes":["NU"],"countries":["Niue"]},"Pacific/Auckland":{"codes":["NZ"],"countries":["New Zealand"],"comments":["most of New Zealand"]},"Pacific/Chatham":{"codes":["NZ"],"countries":["New Zealand"],"comments":["Chatham Islands"]},"Asia/Muscat":{"codes":["OM"],"countries":["Oman"]},"America/Panama":{"codes":["PA"],"countries":["Panama"]},"America/Lima":{"codes":["PE"],"countries":["Peru"]},"Pacific/Tahiti":{"codes":["PF"],"countries":["French Polynesia"],"comments":["Society Islands"]},"Pacific/Marquesas":{"codes":["PF"],"countries":["French Polynesia"],"comments":["Marquesas Islands"]},"Pacific/Gambier":{"codes":["PF"],"countries":["French Polynesia"],"comments":["Gambier Islands"]},"Pacific/Port_Moresby":{"codes":["PG"],"countries":["Papua New Guinea"],"comments":["most of Papua New Guinea"]},"Pacific/Bougainville":{"codes":["PG"],"countries":["Papua New Guinea"],"comments":["Bougainville"]},"Asia/Manila":{"codes":["PH"],"countries":["Philippines"]},"Asia/Karachi":{"codes":["PK"],"countries":["Pakistan"]},"Europe/Warsaw":{"codes":["PL"],"countries":["Poland"]},"America/Miquelon":{"codes":["PM"],"countries":["St Pierre & Miquelon"]},"Pacific/Pitcairn":{"codes":["PN"],"countries":["Pitcairn"]},"America/Puerto_Rico":{"codes":["PR"],"countries":["Puerto Rico"]},"Asia/Gaza":{"codes":["PS"],"countries":["Palestine"],"comments":["Gaza Strip"]},"Asia/Hebron":{"codes":["PS"],"countries":["Palestine"],"comments":["West Bank"]},"Europe/Lisbon":{"codes":["PT"],"countries":["Portugal"],"comments":["Portugal (mainland)"]},"Atlantic/Madeira":{"codes":["PT"],"countries":["Portugal"],"comments":["Madeira Islands"]},"Atlantic/Azores":{"codes":["PT"],"countries":["Portugal"],"comments":["Azores"]},"Pacific/Palau":{"codes":["PW"],"countries":["Palau"]},"America/Asuncion":{"codes":["PY"],"countries":["Paraguay"]},"Asia/Qatar":{"codes":["QA"],"countries":["Qatar"]},"Indian/Reunion":{"codes":["RE"],"countries":["Réunion"]},"Europe/Bucharest":{"codes":["RO"],"countries":["Romania"]},"Europe/Belgrade":{"codes":["RS"],"countries":["Serbia"]},"Europe/Kaliningrad":{"codes":["RU"],"countries":["Russia"],"comments":["MSK-01 - Kaliningrad"]},"Europe/Moscow":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+00 - Moscow area"]},"Europe/Simferopol":{"codes":["UA"],"countries":["Ukraine"],"comments":["Crimea"]},"Europe/Kirov":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+00 - Kirov"]},"Europe/Volgograd":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+00 - Volgograd"]},"Europe/Astrakhan":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+01 - Astrakhan"]},"Europe/Saratov":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+01 - Saratov"]},"Europe/Ulyanovsk":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+01 - Ulyanovsk"]},"Europe/Samara":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+01 - Samara, Udmurtia"]},"Asia/Yekaterinburg":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+02 - Urals"]},"Asia/Omsk":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+03 - Omsk"]},"Asia/Novosibirsk":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+04 - Novosibirsk"]},"Asia/Barnaul":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+04 - Altai"]},"Asia/Tomsk":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+04 - Tomsk"]},"Asia/Novokuznetsk":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+04 - Kemerovo"]},"Asia/Krasnoyarsk":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+04 - Krasnoyarsk area"]},"Asia/Irkutsk":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+05 - Irkutsk, Buryatia"]},"Asia/Chita":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+06 - Zabaykalsky"]},"Asia/Yakutsk":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+06 - Lena River"]},"Asia/Khandyga":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+06 - Tomponsky, Ust-Maysky"]},"Asia/Vladivostok":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+07 - Amur River"]},"Asia/Ust-Nera":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+07 - Oymyakonsky"]},"Asia/Magadan":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+08 - Magadan"]},"Asia/Sakhalin":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+08 - Sakhalin Island"]},"Asia/Srednekolymsk":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+08 - Sakha (E), N Kuril Is"]},"Asia/Kamchatka":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+09 - Kamchatka"]},"Asia/Anadyr":{"codes":["RU"],"countries":["Russia"],"comments":["MSK+09 - Bering Sea"]},"Africa/Kigali":{"codes":["RW"],"countries":["Rwanda"]},"Asia/Riyadh":{"codes":["SA"],"countries":["Saudi Arabia"]},"Pacific/Guadalcanal":{"codes":["SB"],"countries":["Solomon Islands"]},"Indian/Mahe":{"codes":["SC"],"countries":["Seychelles"]},"Africa/Khartoum":{"codes":["SD"],"countries":["Sudan"]},"Europe/Stockholm":{"codes":["SE"],"countries":["Sweden"]},"Asia/Singapore":{"codes":["SG"],"countries":["Singapore"]},"Atlantic/St_Helena":{"codes":["SH"],"countries":["St Helena"]},"Europe/Ljubljana":{"codes":["SI"],"countries":["Slovenia"]},"Arctic/Longyearbyen":{"codes":["SJ"],"countries":["Svalbard & Jan Mayen"]},"Europe/Bratislava":{"codes":["SK"],"countries":["Slovakia"]},"Africa/Freetown":{"codes":["SL"],"countries":["Sierra Leone"]},"Europe/San_Marino":{"codes":["SM"],"countries":["San Marino"]},"Africa/Dakar":{"codes":["SN"],"countries":["Senegal"]},"Africa/Mogadishu":{"codes":["SO"],"countries":["Somalia"]},"America/Paramaribo":{"codes":["SR"],"countries":["Suriname"]},"Africa/Juba":{"codes":["SS"],"countries":["South Sudan"]},"Africa/Sao_Tome":{"codes":["ST"],"countries":["Sao Tome & Principe"]},"America/El_Salvador":{"codes":["SV"],"countries":["El Salvador"]},"America/Lower_Princes":{"codes":["SX"],"countries":["St Maarten (Dutch)"]},"Asia/Damascus":{"codes":["SY"],"countries":["Syria"]},"Africa/Mbabane":{"codes":["SZ"],"countries":["Eswatini (Swaziland)"]},"America/Grand_Turk":{"codes":["TC"],"countries":["Turks & Caicos Is"]},"Africa/Ndjamena":{"codes":["TD"],"countries":["Chad"]},"Indian/Kerguelen":{"codes":["TF"],"countries":["French S. Terr."]},"Africa/Lome":{"codes":["TG"],"countries":["Togo"]},"Asia/Bangkok":{"codes":["TH"],"countries":["Thailand"]},"Asia/Dushanbe":{"codes":["TJ"],"countries":["Tajikistan"]},"Pacific/Fakaofo":{"codes":["TK"],"countries":["Tokelau"]},"Asia/Dili":{"codes":["TL"],"countries":["East Timor"]},"Asia/Ashgabat":{"codes":["TM"],"countries":["Turkmenistan"]},"Africa/Tunis":{"codes":["TN"],"countries":["Tunisia"]},"Pacific/Tongatapu":{"codes":["TO"],"countries":["Tonga"]},"Europe/Istanbul":{"codes":["TR"],"countries":["Turkey"]},"America/Port_of_Spain":{"codes":["TT"],"countries":["Trinidad & Tobago"]},"Pacific/Funafuti":{"codes":["TV"],"countries":["Tuvalu"]},"Asia/Taipei":{"codes":["TW"],"countries":["Taiwan"]},"Africa/Dar_es_Salaam":{"codes":["TZ"],"countries":["Tanzania"]},"Europe/Kyiv":{"codes":["UA"],"countries":["Ukraine"],"comments":["most of Ukraine"]},"Africa/Kampala":{"codes":["UG"],"countries":["Uganda"]},"Pacific/Midway":{"codes":["UM"],"countries":["US minor outlying islands"],"comments":["Midway Islands"]},"Pacific/Wake":{"codes":["UM"],"countries":["US minor outlying islands"],"comments":["Wake Island"]},"America/New_York":{"codes":["US"],"countries":["United States"],"comments":["Eastern (most areas)"]},"America/Detroit":{"codes":["US"],"countries":["United States"],"comments":["Eastern - MI (most areas)"]},"America/Kentucky/Louisville":{"codes":["US"],"countries":["United States"],"comments":["Eastern - KY (Louisville area)"]},"America/Kentucky/Monticello":{"codes":["US"],"countries":["United States"],"comments":["Eastern - KY (Wayne)"]},"America/Indiana/Indianapolis":{"codes":["US"],"countries":["United States"],"comments":["Eastern - IN (most areas)"]},"America/Indiana/Vincennes":{"codes":["US"],"countries":["United States"],"comments":["Eastern - IN (Da, Du, K, Mn)"]},"America/Indiana/Winamac":{"codes":["US"],"countries":["United States"],"comments":["Eastern - IN (Pulaski)"]},"America/Indiana/Marengo":{"codes":["US"],"countries":["United States"],"comments":["Eastern - IN (Crawford)"]},"America/Indiana/Petersburg":{"codes":["US"],"countries":["United States"],"comments":["Eastern - IN (Pike)"]},"America/Indiana/Vevay":{"codes":["US"],"countries":["United States"],"comments":["Eastern - IN (Switzerland)"]},"America/Chicago":{"codes":["US"],"countries":["United States"],"comments":["Central (most areas)"]},"America/Indiana/Tell_City":{"codes":["US"],"countries":["United States"],"comments":["Central - IN (Perry)"]},"America/Indiana/Knox":{"codes":["US"],"countries":["United States"],"comments":["Central - IN (Starke)"]},"America/Menominee":{"codes":["US"],"countries":["United States"],"comments":["Central - MI (Wisconsin border)"]},"America/North_Dakota/Center":{"codes":["US"],"countries":["United States"],"comments":["Central - ND (Oliver)"]},"America/North_Dakota/New_Salem":{"codes":["US"],"countries":["United States"],"comments":["Central - ND (Morton rural)"]},"America/North_Dakota/Beulah":{"codes":["US"],"countries":["United States"],"comments":["Central - ND (Mercer)"]},"America/Denver":{"codes":["US"],"countries":["United States"],"comments":["Mountain (most areas)"]},"America/Boise":{"codes":["US"],"countries":["United States"],"comments":["Mountain - ID (south), OR (east)"]},"America/Phoenix":{"codes":["US"],"countries":["United States"],"comments":["MST - AZ (except Navajo)"]},"America/Los_Angeles":{"codes":["US"],"countries":["United States"],"comments":["Pacific"]},"America/Anchorage":{"codes":["US"],"countries":["United States"],"comments":["Alaska (most areas)"]},"America/Juneau":{"codes":["US"],"countries":["United States"],"comments":["Alaska - Juneau area"]},"America/Sitka":{"codes":["US"],"countries":["United States"],"comments":["Alaska - Sitka area"]},"America/Metlakatla":{"codes":["US"],"countries":["United States"],"comments":["Alaska - Annette Island"]},"America/Yakutat":{"codes":["US"],"countries":["United States"],"comments":["Alaska - Yakutat"]},"America/Nome":{"codes":["US"],"countries":["United States"],"comments":["Alaska (west)"]},"America/Adak":{"codes":["US"],"countries":["United States"],"comments":["Alaska - western Aleutians"]},"Pacific/Honolulu":{"codes":["US"],"countries":["United States"],"comments":["Hawaii"]},"America/Montevideo":{"codes":["UY"],"countries":["Uruguay"]},"Asia/Samarkand":{"codes":["UZ"],"countries":["Uzbekistan"],"comments":["Uzbekistan (west)"]},"Asia/Tashkent":{"codes":["UZ"],"countries":["Uzbekistan"],"comments":["Uzbekistan (east)"]},"Europe/Vatican":{"codes":["VA"],"countries":["Vatican City"]},"America/St_Vincent":{"codes":["VC"],"countries":["St Vincent"]},"America/Caracas":{"codes":["VE"],"countries":["Venezuela"]},"America/Tortola":{"codes":["VG"],"countries":["Virgin Islands (UK)"]},"America/St_Thomas":{"codes":["VI"],"countries":["Virgin Islands (US)"]},"Asia/Ho_Chi_Minh":{"codes":["VN"],"countries":["Vietnam"]},"Pacific/Efate":{"codes":["VU"],"countries":["Vanuatu"]},"Pacific/Wallis":{"codes":["WF"],"countries":["Wallis & Futuna"]},"Pacific/Apia":{"codes":["WS"],"countries":["Samoa (western)"]},"Asia/Aden":{"codes":["YE"],"countries":["Yemen"]},"Indian/Mayotte":{"codes":["YT"],"countries":["Mayotte"]},"Africa/Johannesburg":{"codes":["ZA"],"countries":["South Africa"]},"Africa/Lusaka":{"codes":["ZM"],"countries":["Zambia"]},"Africa/Harare":{"codes":["ZW"],"countries":["Zimbabwe"]}};

  // Human search aliases that are useful to attendees but are not IANA TZIDs.
  // Abu Dhabi intentionally maps to the UAE's standard IANA zone, Asia/Dubai.
  const EXTRA_SEARCH_ALIASES = {
    'Asia/Dubai': ['Abu Dhabi', 'UAE', 'Emirates'],
    'Europe/London': ['UK', 'Britain', 'Great Britain'],
  };

  const COUNTRY_CODE_SEARCH_ALIASES = {
    US: ['USA', 'United States of America'],
    GB: ['UK', 'United Kingdom', 'Britain', 'Great Britain'],
    AE: ['UAE', 'Emirates'],
    KR: ['South Korea'],
    KP: ['North Korea'],
    RU: ['Russia'],
    VN: ['Vietnam'],
    LA: ['Laos'],
    BO: ['Bolivia'],
    TZ: ['Tanzania'],
    VE: ['Venezuela'],
    BN: ['Brunei'],
  };

  const FALLBACK_ZONES = [
    'Pacific/Honolulu','America/Anchorage','America/Los_Angeles','America/Phoenix','America/Denver',
    'America/Chicago','America/New_York','America/Toronto','America/Bogota','America/Lima',
    'America/Santiago','America/Argentina/Buenos_Aires','America/Sao_Paulo','Atlantic/Reykjavik',
    'Europe/London','Europe/Dublin','Europe/Lisbon','Europe/Madrid','Europe/Paris','Europe/Berlin',
    'Europe/Rome','Europe/Athens','Europe/Helsinki','Europe/Istanbul','Europe/Moscow','Africa/Accra',
    'Africa/Blantyre','Africa/Lagos','Africa/Johannesburg','Africa/Cairo','Africa/Nairobi','Asia/Jerusalem',
    'Asia/Riyadh','Asia/Dubai','Asia/Tehran','Asia/Karachi','Asia/Kolkata','Asia/Kathmandu','Asia/Dhaka',
    'Asia/Bangkok','Asia/Jakarta','Asia/Singapore','Asia/Hong_Kong','Asia/Shanghai','Asia/Taipei',
    'Asia/Seoul','Asia/Tokyo','Australia/Perth','Australia/Brisbane','Australia/Sydney',
    'Australia/Melbourne','Pacific/Auckland','Pacific/Fiji'
  ];

  const STATIC_ABBREVIATIONS = {
    'Asia/Shanghai': 'CST', 'Asia/Taipei': 'CST', 'Asia/Tokyo': 'JST', 'Asia/Seoul': 'KST',
    'Asia/Hong_Kong': 'HKT', 'Asia/Singapore': 'SGT', 'Asia/Bangkok': 'ICT', 'Asia/Jakarta': 'WIB',
    'Asia/Kolkata': 'IST', 'Asia/Kathmandu': 'NPT', 'Asia/Dhaka': 'BST', 'Asia/Karachi': 'PKT',
    'Asia/Tehran': 'IRST', 'Asia/Dubai': 'GST', 'Asia/Riyadh': 'AST', 'Europe/Istanbul': 'TRT',
    'Europe/Moscow': 'MSK', 'Atlantic/Reykjavik': 'GMT', 'Africa/Johannesburg': 'SAST',
    'Africa/Nairobi': 'EAT', 'Africa/Lagos': 'WAT', 'Africa/Accra': 'GMT', 'America/Phoenix': 'MST',
    'Pacific/Honolulu': 'HST', 'America/Bogota': 'COT', 'America/Lima': 'PET',
    'America/Argentina/Buenos_Aires': 'ART', 'America/Sao_Paulo': 'BRT', 'Australia/Brisbane': 'AEST',
    'Australia/Perth': 'AWST', 'Pacific/Fiji': 'FJT'
  };

  function browserZone() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || FALLBACK_ZONE; }
    catch (_) { return FALLBACK_ZONE; }
  }

  function validZone(candidate) {
    if (!candidate) return false;
    try { new Intl.DateTimeFormat('en', { timeZone: candidate }).format(new Date()); return true; }
    catch (_) { return false; }
  }

  function supportedZones() {
    const candidates = new Set([...FALLBACK_ZONES, ...Object.keys(IANA_ZONE_SEARCH_META)]);
    try {
      if (typeof Intl.supportedValuesOf === 'function') {
        for (const timeZone of Intl.supportedValuesOf('timeZone')) candidates.add(timeZone);
      }
    } catch (_) {}
    return [...candidates].filter(validZone).sort((a, b) => a.localeCompare(b, 'en'));
  }

  const ALL_ZONES = supportedZones();
  let zone = browserZone();
  if (!validZone(zone)) zone = FALLBACK_ZONE;
  let referenceDate = new Date();

  function dateValue(value, fallback = new Date()) {
    if (value instanceof Date && Number.isFinite(value.getTime())) return value;
    const parsed = new Date(value);
    return Number.isFinite(parsed.getTime()) ? parsed : fallback;
  }

  function longOffsetParts(timeZone, date = new Date()) {
    const instant = dateValue(date);
    try {
      const raw = new Intl.DateTimeFormat('en-US', {
        timeZone,
        timeZoneName: 'longOffset',
        hour: '2-digit',
      }).formatToParts(instant).find((part) => part.type === 'timeZoneName')?.value || 'GMT';
      if (raw === 'GMT' || raw === 'UTC') return { minutes: 0, text: 'UTC+0' };
      const match = raw.match(/(?:GMT|UTC)([+-])(\d{1,2})(?::(\d{2}))?/);
      if (!match) return { minutes: 0, text: 'UTC+0' };
      const sign = match[1] === '-' ? -1 : 1;
      const hours = Number(match[2] || 0);
      const minutes = Number(match[3] || 0);
      const total = sign * (hours * 60 + minutes);
      const suffix = minutes ? `:${String(minutes).padStart(2, '0')}` : '';
      return { minutes: total, text: `UTC${match[1]}${hours}${suffix}` };
    } catch (_) {
      return { minutes: 0, text: 'UTC+0' };
    }
  }

  function daylightAbbreviation(timeZone, offsetMinutes) {
    if (timeZone === 'Europe/London' || timeZone === 'Europe/Dublin') return offsetMinutes === 60 ? 'BST' : 'GMT';
    if (['Europe/Berlin','Europe/Paris','Europe/Rome','Europe/Madrid'].includes(timeZone)) return offsetMinutes === 120 ? 'CEST' : 'CET';
    if (['Europe/Athens','Europe/Helsinki'].includes(timeZone)) return offsetMinutes === 180 ? 'EEST' : 'EET';
    if (timeZone === 'Asia/Jerusalem') return offsetMinutes === 180 ? 'IDT' : 'IST';
    if (['Australia/Sydney','Australia/Melbourne'].includes(timeZone)) return offsetMinutes === 660 ? 'AEDT' : 'AEST';
    if (timeZone === 'Pacific/Auckland') return offsetMinutes === 780 ? 'NZDT' : 'NZST';
    if (timeZone === 'America/Santiago') return offsetMinutes === -180 ? 'CLST' : 'CLT';
    return '';
  }

  function abbreviation(timeZone, date = new Date()) {
    const instant = dateValue(date);
    const { minutes } = longOffsetParts(timeZone, instant);
    const dynamic = daylightAbbreviation(timeZone, minutes);
    if (dynamic) return dynamic;
    try {
      const raw = new Intl.DateTimeFormat('en-US', {
        timeZone,
        timeZoneName: 'short',
        hour: '2-digit',
      }).formatToParts(instant).find((part) => part.type === 'timeZoneName')?.value || '';
      if (/^[A-Z]{2,6}$/.test(raw) && !/^(GMT|UTC)$/.test(raw)) return raw;
    } catch (_) {}
    return STATIC_ABBREVIATIONS[timeZone] || '';
  }

  function offsetLabel(timeZone = zone, date = referenceDate) {
    const instant = dateValue(date, referenceDate);
    const offset = longOffsetParts(timeZone, instant).text;
    const abbr = abbreviation(timeZone, instant);
    return abbr ? `${offset} (${abbr})` : offset;
  }

  function utcOffsetLabel(timeZone = zone, date = referenceDate) {
    return longOffsetParts(timeZone, dateValue(date, referenceDate)).text;
  }

  function zoneSummary(timeZone = zone, date = referenceDate) {
    return `${timeZone} (${utcOffsetLabel(timeZone, date)})`;
  }

  function normalizeText(value) {
    return String(value || '')
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[_/\\-]+/g, ' ')
      .replace(/[^\p{L}\p{N}:+]+/gu, ' ')
      .trim()
      .replace(/\s+/g, ' ');
  }

  let regionDisplayNames = null;
  try {
    if (typeof Intl.DisplayNames === 'function') {
      regionDisplayNames = new Intl.DisplayNames([navigator.language || 'en', 'en'], { type: 'region' });
    }
  } catch (_) {}

  function localizedCountryNames(codes) {
    if (!regionDisplayNames) return [];
    return (codes || []).map((code) => {
      try { return regionDisplayNames.of(code) || ''; } catch (_) { return ''; }
    }).filter(Boolean);
  }

  function searchTermsForZone(timeZone) {
    const meta = IANA_ZONE_SEARCH_META[timeZone] || {};
    const codes = meta.codes || [];
    const aliases = [
      ...(EXTRA_SEARCH_ALIASES[timeZone] || []),
      ...codes.flatMap((code) => COUNTRY_CODE_SEARCH_ALIASES[code] || []),
    ];
    const humanZone = timeZone.replace(/_/g, ' ').replace(/\//g, ' ');
    return [
      timeZone,
      humanZone,
      utcOffsetLabel(timeZone, referenceDate),
      ...codes,
      ...(meta.countries || []),
      ...localizedCountryNames(codes),
      ...(meta.comments || []),
      ...aliases,
    ].filter(Boolean);
  }

  function searchScore(timeZone, needle) {
    const normalizedZone = normalizeText(timeZone);
    const terms = searchTermsForZone(timeZone).map(normalizeText);
    if (normalizedZone === needle) return 0;
    if (normalizedZone.startsWith(needle)) return 1;
    if (terms.some((term) => term === needle)) return 2;
    if (terms.some((term) => term.startsWith(needle))) return 3;
    return 4;
  }

  function updateControlNode(control) {
    if (!control) return;
    const summary = control.querySelector('[data-timezone-summary]');
    if (summary) summary.textContent = zoneSummary(zone);
    const trigger = control.querySelector('[data-timezone-trigger]');
    if (trigger) trigger.title = `Current time zone: ${zoneSummary(zone)}. Click to change.`;
  }

  function updateControls() {
    updateControlNode(document.getElementById('user-timezone-control'));
    updateControlNode(document.getElementById('debug-timezone-control'));
  }

  let dropdown = null;
  let activeTrigger = null;
  let highlighted = -1;
  let visibleZones = [];

  function optionLabel(timeZone) {
    return `${timeZone} (${utcOffsetLabel(timeZone, referenceDate)})`;
  }

  function filteredZones(query) {
    const needle = normalizeText(query);
    if (!needle) return ALL_ZONES;
    const tokens = needle.split(' ').filter(Boolean);
    return ALL_ZONES
      .filter((timeZone) => {
        const haystack = normalizeText(searchTermsForZone(timeZone).join(' '));
        return tokens.every((token) => haystack.includes(token));
      })
      .sort((a, b) => searchScore(a, needle) - searchScore(b, needle) || a.localeCompare(b, 'en'));
  }

  function ensureDropdown() {
    if (dropdown) return dropdown;
    const node = document.createElement('div');
    node.className = 'timezone-dropdown';
    node.hidden = true;
    node.innerHTML = `
      <div class="timezone-dropdown-search-row">
        <input class="timezone-dropdown-search" type="text" autocomplete="off" spellcheck="false" placeholder="Search time zone..." role="combobox" aria-autocomplete="list" aria-expanded="true" aria-controls="timezone-dropdown-options">
      </div>
      <div class="timezone-dropdown-options" id="timezone-dropdown-options" role="listbox"></div>`;
    document.body.appendChild(node);

    const input = node.querySelector('.timezone-dropdown-search');
    const options = node.querySelector('.timezone-dropdown-options');

    input.addEventListener('input', () => renderOptions(input.value));
    input.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        highlightOption(highlighted + 1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        highlightOption(highlighted - 1);
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (highlighted >= 0 && visibleZones[highlighted]) chooseZone(visibleZones[highlighted]);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        closeDropdown();
      }
    });

    options.addEventListener('mousedown', (event) => event.preventDefault());
    options.addEventListener('click', (event) => {
      const item = event.target.closest('[data-timezone-option]');
      if (item) chooseZone(item.dataset.timezoneOption);
    });

    dropdown = node;
    return dropdown;
  }

  function renderOptions(query = '') {
    const node = ensureDropdown();
    const options = node.querySelector('.timezone-dropdown-options');
    visibleZones = filteredZones(query).slice(0, 180);
    highlighted = visibleZones.length ? Math.max(0, visibleZones.indexOf(zone)) : -1;
    if (highlighted < 0 && visibleZones.length) highlighted = 0;
    options.innerHTML = visibleZones.length
      ? visibleZones.map((timeZone, index) => `<button type="button" class="timezone-dropdown-option${index === highlighted ? ' is-highlighted' : ''}" role="option" data-timezone-option="${timeZone}">${optionLabel(timeZone)}</button>`).join('')
      : '<div class="timezone-dropdown-empty">No matching time zone</div>';
  }

  function highlightOption(index) {
    if (!visibleZones.length || !dropdown) return;
    highlighted = (index + visibleZones.length) % visibleZones.length;
    const options = [...dropdown.querySelectorAll('.timezone-dropdown-option')];
    options.forEach((option, i) => option.classList.toggle('is-highlighted', i === highlighted));
    options[highlighted]?.scrollIntoView({ block: 'nearest' });
  }

  function positionDropdown() {
    if (!dropdown || !activeTrigger || dropdown.hidden) return;
    const rect = activeTrigger.getBoundingClientRect();
    const gap = 7;
    const width = Math.min(390, Math.max(300, rect.width + 120));
    let left = rect.left;
    if (left + width > window.innerWidth - 12) left = window.innerWidth - width - 12;
    left = Math.max(12, left);
    let top = rect.bottom + gap;
    const estimatedHeight = Math.min(390, window.innerHeight * 0.58);
    if (top + estimatedHeight > window.innerHeight - 12 && rect.top > estimatedHeight) {
      top = Math.max(12, rect.top - estimatedHeight - gap);
    }
    dropdown.style.left = `${Math.round(left)}px`;
    dropdown.style.top = `${Math.round(top)}px`;
    dropdown.style.width = `${Math.round(width)}px`;
  }

  function openDropdown(trigger) {
    activeTrigger = trigger;
    const node = ensureDropdown();
    const input = node.querySelector('.timezone-dropdown-search');
    node.hidden = false;
    input.value = '';
    renderOptions('');
    positionDropdown();
    requestAnimationFrame(() => {
      node.classList.add('is-open');
      input.focus({ preventScroll: true });
      const active = node.querySelector('.timezone-dropdown-option.is-highlighted');
      active?.scrollIntoView({ block: 'nearest' });
    });
  }

  function closeDropdown() {
    if (!dropdown || dropdown.hidden) return;
    dropdown.classList.remove('is-open');
    dropdown.hidden = true;
    activeTrigger = null;
  }

  function chooseZone(nextZone) {
    if (setZone(nextZone)) closeDropdown();
  }

  function notify() {
    updateControls();
    if (dropdown && !dropdown.hidden) renderOptions(dropdown.querySelector('.timezone-dropdown-search')?.value || '');
    window.dispatchEvent(new CustomEvent('ismir-timezone-change', {
      detail: { timeZone: zone, offset: offsetLabel(zone), summary: zoneSummary(zone) },
    }));
  }

  function setReferenceDate(value) {
    const date = dateValue(value, null);
    if (!date || !Number.isFinite(date.getTime())) return false;
    referenceDate = date;
    updateControls();
    if (dropdown && !dropdown.hidden) renderOptions(dropdown.querySelector('.timezone-dropdown-search')?.value || '');
    return true;
  }

  function setZone(nextZone) {
    const candidate = String(nextZone || '').trim();
    if (!validZone(candidate)) return false;
    zone = candidate;
    notify();
    return true;
  }

  function init() {
    updateControls();
    document.querySelectorAll('[data-timezone-trigger]').forEach((trigger) => {
      trigger.addEventListener('click', (event) => {
        event.stopPropagation();
        if (dropdown && !dropdown.hidden && activeTrigger === trigger) closeDropdown();
        else openDropdown(trigger);
      });
    });
    document.addEventListener('mousedown', (event) => {
      if (!dropdown || dropdown.hidden) return;
      if (dropdown.contains(event.target) || activeTrigger?.contains(event.target)) return;
      closeDropdown();
    });
    window.addEventListener('resize', positionDropdown);
    window.addEventListener('scroll', positionDropdown, true);
    window.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && dropdown && !dropdown.hidden) closeDropdown();
    });
  }

  window.ISMIRTimeZone = {
    getTimeZone: () => zone,
    getOffsetLabel: (date) => offsetLabel(zone, date == null ? referenceDate : date),
    getUTCOffset: (date) => utcOffsetLabel(zone, date == null ? referenceDate : date),
    getSummary: (date) => zoneSummary(zone, date == null ? referenceDate : date),
    setTimeZone: setZone,
    setReferenceDate,
    openPicker: openDropdown,
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
