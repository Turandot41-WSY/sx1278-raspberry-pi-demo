"""Share exact CSV field names between the radio tables and their loader."""

# Project choices: fixed field order prevents ambiguous radio configuration.

SCHEMA_VERSION = 1

PROFILE_COLUMNS = (
    "ProfileId",
    "ProfileCode",
    "Family",
    "Modulation",
    "CarrierHz",
    "AllocatedBandwidthHz",
    "RegBitRate",
    "RegFdev",
    "SpreadingFactor",
    "CodingRateDenominator",
    "ImplicitHeader",
    "PreambleUnits",
    "PreambleUnit",
    "SyncWordHex",
    "Whitening",
    "PhyCrc",
    "GaussianBt",
    "RxBwRegister",
    "NominalAirtimeMs",
    "IdealApplicationGoodputKbps",
)

PA_SETTING_COLUMNS = (
    "PaCommandDbm",
    "RegPaConfig",
    "RegPaDac",
    "RegOcp",
)

PROFILE_REGISTER_COLUMNS = (
    "ProfileId",
    "Bank",
    "Address",
    "WriteValue",
    "ReadbackMask",
    "ExpectedReadback",
    "WriteOrder",
    "DatasheetRevision",
    "SourceSectionOrTable",
    "ProjectReason",
)
