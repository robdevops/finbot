def get_url(symbol, name, exchange):
    sws = {}
    sws['1415.HK'] = 'https://simplywall.st/stocks/hk/tech/hkg-1415/cowell-e-holdings-shares'
    sws['A4N.AX'] = 'https://simplywall.st/stocks/au/materials/asx-a4n/alpha-hpa-shares'
    sws['AAPL'] = 'https://simplywall.st/stocks/us/tech/nasdaq-aapl/apple'
    sws['ACMR'] = 'https://simplywall.st/stocks/us/semiconductors/nasdaq-acmr/acm-research'
    sws['AD8.AX'] = 'https://simplywall.st/stocks/au/tech/asx-ad8/audinate-group-shares'
    sws['ADSK'] = 'https://simplywall.st/stocks/us/software/nasdaq-adsk/autodesk'
    sws['AIS.AX'] = 'https://simplywall.st/stocks/au/materials/asx-ais/aeris-resources-shares'
    sws['ALU.AX'] = 'https://simplywall.st/stocks/au/software/asx-alu/altium-shares'
    sws['AMD'] = 'https://simplywall.st/stocks/us/semiconductors/nasdaq-amd/advanced-micro-devices'
    sws['AMPG'] = 'https://simplywall.st/stocks/us/tech/nasdaq-ampg/amplitech-group'
    sws['AMPX'] = 'https://simplywall.st/stocks/us/capital-goods/nyse-ampx/amprius-technologies'
    sws['ARR.AX'] = 'https://simplywall.st/stocks/au/materials/asx-arr/american-rare-earths-shares'
    sws['ARU.AX'] = 'https://simplywall.st/stocks/au/materials/asx-aru/arafura-rare-earths-shares'
    sws['ASML'] = 'https://simplywall.st/stocks/nl/semiconductors/ams-asml/asml-holding-shares'
    sws['ASMR'] = 'https://simplywall.st/stocks/us/semiconductors/nasdaq-acmr/acm-research'
    sws['ASO.AX'] = 'https://simplywall.st/stocks/au/materials/asx-aso/aston-minerals-shares'
    sws['ATC.AX'] = 'https://simplywall.st/stocks/au/materials/asx-atc/altech-batteries-shares'
    sws['AWE.L'] = 'https://simplywall.st/stocks/gb/semiconductors/lse-awe/alphawave-ip-group-shares'
    sws['AXE.AX'] = 'https://simplywall.st/stocks/au/semiconductors/asx-axe/archer-materials-shares'
    sws['BKG.AX'] = 'https://simplywall.st/stocks/au/retail/asx-bkg/booktopia-group-shares'
    sws['BKSY'] = 'https://simplywall.st/stocks/us/commercial-services/nyse-bksy/blacksky-technology'
    sws['BLFS'] = 'https://simplywall.st/stocks/us/pharmaceuticals-biotech/nasdaq-blfs/biolife-solutions'
    sws['CODX'] = 'https://simplywall.st/stocks/us/healthcare/nasdaq-codx/co-diagnostics'
    sws['CRWD'] = 'https://simplywall.st/stocks/us/software/nasdaq-crwd/crowdstrike-holdings'
    sws['CSL.AX'] = 'https://simplywall.st/stocks/au/pharmaceuticals-biotech/asx-csl/csl-shares'
    sws['CXL.AX'] = 'https://simplywall.st/stocks/au/materials/asx-cxl/calix-shares'
    sws['DIS'] = 'https://simplywall.st/stocks/us/media/nyse-dis/walt-disney'
    sws['DMP.AX'] = 'https://simplywall.st/stocks/au/consumer-services/asx-dmp/dominos-pizza-enterprises-shares'
    sws['DUB.AX'] = 'https://simplywall.st/stocks/au/software/asx-dub/dubber-shares'
    sws['DUOL'] = 'https://simplywall.st/stocks/us/consumer-services/nasdaq-duol/duolingo'
    sws['ENPH'] = 'https://simplywall.st/stocks/us/semiconductors/nasdaq-enph/enphase-energy'
    sws['ERM.AX'] = 'https://simplywall.st/stocks/au/materials/asx-erm/emmerson-resources-shares'
    sws['FDV.AX'] = 'https://simplywall.st/stocks/au/media/asx-fdv/frontier-digital-ventures-shares'
    sws['FSLR'] = 'https://simplywall.st/stocks/us/semiconductors/nasdaq-fslr/first-solar'
    sws['FTNT'] = 'https://simplywall.st/stocks/us/software/nasdaq-ftnt/fortinet'
    sws['HCP'] = 'https://simplywall.st/stocks/us/software/nasdaq-hcp/hashicorp'
    sws['GOOG'] = 'https://simplywall.st/stocks/us/media/nasdaq-goog/alphabet'
    sws['GOOGL'] = 'https://simplywall.st/stocks/us/media/nasdaq-goog/alphabet'
    sws['GTK.AX'] = 'https://simplywall.st/stocks/nz/software/nzx-gtk/gentrack-group-shares'
    sws['GTLB'] = 'https://simplywall.st/stocks/us/software/nasdaq-gtlb/gitlab'
    sws['GWH'] = 'https://simplywall.st/stocks/us/capital-goods/nyse-gwh/ess-tech'
    sws['IKE.AX'] = 'https://simplywall.st/stocks/nz/tech/nzx-ike/ikegps-group-shares'
    sws['ILMN'] = 'https://simplywall.st/stocks/us/pharmaceuticals-biotech/nasdaq-ilmn/illumina'
    sws['INR.AX'] = 'https://simplywall.st/stocks/au/materials/asx-inr/ioneer-shares'
    sws['INTU'] = 'https://simplywall.st/stocks/us/software/nasdaq-intu/intuit'
    sws['ITM.AX'] = 'https://simplywall.st/stocks/au/materials/asx-itm/itech-minerals-shares'
    sws['LBT.AX'] = 'https://simplywall.st/stocks/au/healthcare/asx-lbt/lbt-innovations-shares'
    sws['LIS.AX'] = 'https://simplywall.st/stocks/au/capital-goods/asx-lis/li-s-energy-shares'
    sws['LOV.AX'] = 'https://simplywall.st/stocks/au/retail/asx-lov/lovisa-holdings-shares'
    sws['LRK.AX'] = 'https://simplywall.st/stocks/au/food-beverage-tobacco/asx-lrk/lark-distilling-shares'
    sws['LSCC'] = 'https://simplywall.st/stocks/us/semiconductors/nasdaq-lscc/lattice-semiconductor'
    sws['LYC.AX'] = 'https://simplywall.st/stocks/au/materials/asx-lyc/lynas-rare-earths-shares'
    sws['MAP.AX'] = 'https://simplywall.st/stocks/au/healthcare/asx-map/microba-life-sciences-shares'
    sws['MP1.AX'] = 'https://simplywall.st/stocks/au/software/asx-mp1/megaport-shares'
    sws['MRNA'] = 'https://simplywall.st/stocks/us/pharmaceuticals-biotech/nasdaq-mrna/moderna'
    sws['MSFT'] = 'https://simplywall.st/stocks/us/software/nasdaq-msft/microsoft'
    sws['NANO.TO'] = 'https://simplywall.st/stocks/ca/materials/tsx-nano/nano-one-materials-shares'
    sws['NOW'] = 'https://simplywall.st/stocks/us/software/nyse-now/servicenow'
    sws['NRGV'] = 'https://simplywall.st/stocks/us/capital-goods/nyse-nrgv/energy-vault-holdings'
    sws['NVDA'] = 'https://simplywall.st/stocks/us/semiconductors/nasdaq-nvda/nvidia'
    sws['NWC.AX'] = 'https://simplywall.st/stocks/au/materials/asx-nwc/new-world-resources-shares'
    sws['NXD'] = 'https://simplywall.st/stocks/au/consumer-services/asx-nxd/nexted-group-shares'
    sws['ORG.AX'] = 'https://simplywall.st/stocks/au/utilities/asx-org/origin-energy-shares'
    sws['PAYC'] = 'https://simplywall.st/stocks/us/commercial-services/nyse-payc/paycom-software'
    sws['PLL.AX'] = 'https://simplywall.st/stocks/au/materials/asx-pll/piedmont-lithium-shares'
    sws['PME.AX'] = 'https://simplywall.st/stocks/au/healthcare/asx-pme/pro-medicus-shares'
    sws['PSC.AX'] = 'https://simplywall.st/stocks/au/materials/asx-psc/prospect-resources-shares'
    sws['PYPL'] = 'https://simplywall.st/stocks/us/diversified-financials/nasdaq-pypl/paypal-holdings'
    sws['QCOM'] = 'https://simplywall.st/stocks/us/semiconductors/nasdaq-qcom/qualcomm'
    sws['QSI'] = 'https://simplywall.st/stocks/us/pharmaceuticals-biotech/nasdaq-qsi/quantum-si'
    sws['REA.AX'] = 'https://simplywall.st/stocks/au/media/asx-rea/rea-group-shares'
    sws['RKLB'] = 'https://simplywall.st/stocks/us/capital-goods/nasdaq-rklb/rocket-lab-usa'
    sws['RMBS'] = 'https://simplywall.st/stocks/us/semiconductors/nasdaq-rmbs/rambus'
    sws['RUL.AX'] = 'https://simplywall.st/stocks/au/software/asx-rul/rpmglobal-holdings-shares'
    sws['SEDG'] = 'https://simplywall.st/stocks/us/semiconductors/nasdaq-sedg/solaredge-technologies'
    sws['SES'] = 'https://simplywall.st/stocks/us/capital-goods/nyse-ses/ses-ai'
    sws['SFR.AX'] = 'https://simplywall.st/stocks/au/materials/asx-sfr/sandfire-resources-shares'
    sws['SKO.AX'] = 'https://simplywall.st/stocks/nz/software/nzx-sko/serko-shares'
    sws['S'] = 'https://simplywall.st/stocks/us/software/nyse-s/sentinelone'
    sws['SLDP'] = 'https://simplywall.st/stocks/us/automobiles/nasdaq-sldp/solid-power'
    sws['SOFI'] = 'https://simplywall.st/stocks/us/diversified-financials/nasdaq-sofi/sofi-technologies'
    sws['SYA.AX'] = 'https://simplywall.st/stocks/au/materials/asx-sya/sayona-mining-shares'
    sws['SYR.AX'] = 'https://simplywall.st/stocks/au/materials/asx-syr/syrah-resources-shares'
    sws['TEAM'] = 'https://simplywall.st/stocks/us/software/nasdaq-team/atlassian'
    sws['TLG.AX'] = 'https://simplywall.st/stocks/au/materials/asx-tlg/talga-group-shares'
    sws['TNE.AX'] = 'https://simplywall.st/stocks/au/software/asx-tne/technology-one-shares'
    sws['TSLA'] = 'https://simplywall.st/stocks/us/automobiles/nasdaq-tsla/tesla'
    sws['TSM'] = 'https://simplywall.st/stocks/us/semiconductors/nyse-tsm/taiwan-semiconductor-manufacturing'
    sws['U'] = 'https://simplywall.st/stocks/us/software/nyse-u/unity-software'
    sws['WISE.L'] = 'https://simplywall.st/stocks/gb/diversified-financials/lse-wise/wise-shares'
    sws['ZG'] = 'https://simplywall.st/stocks/us/real-estate-management-and-development/nasdaq-zg/zillow-group'
    sws['ZS'] = 'https://simplywall.st/stocks/us/software/nasdaq-zs/zscaler'
    if symbol in sws:
        return sws[symbol]
    else:
        return 'https://www.google.com/search?q=site:simplywall.st+(' + name + '+' + exchange + ':' + symbol.split('.')[0] + ')+Stock&btnI'
