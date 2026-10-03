import json

SDK_VERSION = "1.4.0"
SCHEMA_SOURCE_SHA256 = 'd94a98fab1fd126fa82e6e8e6c2eda6756b516bd5df42dbaaad1b9e9c22f5239'
DESERIALIZE_SOURCE_SHA256 = '1fd2240595b8d813993f08f5816b7503f1acea8acec4186d86cb3b674e101c05'
PARAMETER_SCHEMAS = json.loads(r'''
{
  "initialize": {
    "type": "object",
    "shape": {
      "protocolVersion": {
        "type": "number",
        "format": "safeint",
        "checks": [
          {
            "check": "greater_than",
            "value": 0,
            "inclusive": true
          },
          {
            "check": "less_than",
            "value": 65535,
            "inclusive": true
          }
        ]
      },
      "clientCapabilities": {
        "type": "catch",
        "inner": {
          "type": "default",
          "inner": {
            "type": "optional",
            "inner": {
              "type": "object",
              "shape": {
                "fs": {
                  "type": "catch",
                  "inner": {
                    "type": "default",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "object",
                        "shape": {
                          "readTextFile": {
                            "type": "catch",
                            "inner": {
                              "type": "default",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "boolean"
                                }
                              },
                              "fallback": {
                                "value": false
                              }
                            },
                            "fallback": {
                              "value": false
                            }
                          },
                          "writeTextFile": {
                            "type": "catch",
                            "inner": {
                              "type": "default",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "boolean"
                                }
                              },
                              "fallback": {
                                "value": false
                              }
                            },
                            "fallback": {
                              "value": false
                            }
                          },
                          "_meta": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          }
                        }
                      }
                    },
                    "fallback": {
                      "value": {
                        "readTextFile": false,
                        "writeTextFile": false
                      }
                    }
                  },
                  "fallback": {
                    "value": {
                      "readTextFile": false,
                      "writeTextFile": false
                    }
                  }
                },
                "terminal": {
                  "type": "catch",
                  "inner": {
                    "type": "default",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "boolean"
                      }
                    },
                    "fallback": {
                      "value": false
                    }
                  },
                  "fallback": {
                    "value": false
                  }
                },
                "session": {
                  "type": "catch",
                  "inner": {
                    "type": "optional",
                    "inner": {
                      "type": "nullable",
                      "inner": {
                        "type": "object",
                        "shape": {
                          "compaction": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          },
                          "configOptions": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "object",
                                  "shape": {
                                    "boolean": {
                                      "type": "catch",
                                      "inner": {
                                        "type": "optional",
                                        "inner": {
                                          "type": "nullable",
                                          "inner": {
                                            "type": "object",
                                            "shape": {
                                              "_meta": {
                                                "type": "catch",
                                                "inner": {
                                                  "type": "optional",
                                                  "inner": {
                                                    "type": "nullable",
                                                    "inner": {
                                                      "type": "record",
                                                      "key": {
                                                        "type": "string"
                                                      },
                                                      "value": {
                                                        "type": "unknown"
                                                      }
                                                    }
                                                  }
                                                },
                                                "fallback": {
                                                  "absent": true
                                                }
                                              }
                                            }
                                          }
                                        }
                                      },
                                      "fallback": {
                                        "absent": true
                                      }
                                    },
                                    "_meta": {
                                      "type": "catch",
                                      "inner": {
                                        "type": "optional",
                                        "inner": {
                                          "type": "nullable",
                                          "inner": {
                                            "type": "record",
                                            "key": {
                                              "type": "string"
                                            },
                                            "value": {
                                              "type": "unknown"
                                            }
                                          }
                                        }
                                      },
                                      "fallback": {
                                        "absent": true
                                      }
                                    }
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          },
                          "_meta": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          }
                        }
                      }
                    }
                  },
                  "fallback": {
                    "absent": true
                  }
                },
                "plan": {
                  "type": "catch",
                  "inner": {
                    "type": "optional",
                    "inner": {
                      "type": "nullable",
                      "inner": {
                        "type": "object",
                        "shape": {
                          "_meta": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          }
                        }
                      }
                    }
                  },
                  "fallback": {
                    "absent": true
                  }
                },
                "auth": {
                  "type": "catch",
                  "inner": {
                    "type": "default",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "object",
                        "shape": {
                          "terminal": {
                            "type": "catch",
                            "inner": {
                              "type": "default",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "boolean"
                                }
                              },
                              "fallback": {
                                "value": false
                              }
                            },
                            "fallback": {
                              "value": false
                            }
                          },
                          "_meta": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          }
                        }
                      }
                    },
                    "fallback": {
                      "value": {
                        "terminal": false
                      }
                    }
                  },
                  "fallback": {
                    "value": {
                      "terminal": false
                    }
                  }
                },
                "elicitation": {
                  "type": "catch",
                  "inner": {
                    "type": "optional",
                    "inner": {
                      "type": "nullable",
                      "inner": {
                        "type": "object",
                        "shape": {
                          "form": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "object",
                                  "shape": {
                                    "_meta": {
                                      "type": "catch",
                                      "inner": {
                                        "type": "optional",
                                        "inner": {
                                          "type": "nullable",
                                          "inner": {
                                            "type": "record",
                                            "key": {
                                              "type": "string"
                                            },
                                            "value": {
                                              "type": "unknown"
                                            }
                                          }
                                        }
                                      },
                                      "fallback": {
                                        "absent": true
                                      }
                                    }
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          },
                          "url": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "object",
                                  "shape": {
                                    "_meta": {
                                      "type": "catch",
                                      "inner": {
                                        "type": "optional",
                                        "inner": {
                                          "type": "nullable",
                                          "inner": {
                                            "type": "record",
                                            "key": {
                                              "type": "string"
                                            },
                                            "value": {
                                              "type": "unknown"
                                            }
                                          }
                                        }
                                      },
                                      "fallback": {
                                        "absent": true
                                      }
                                    }
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          },
                          "_meta": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          }
                        }
                      }
                    }
                  },
                  "fallback": {
                    "absent": true
                  }
                },
                "nes": {
                  "type": "catch",
                  "inner": {
                    "type": "optional",
                    "inner": {
                      "type": "nullable",
                      "inner": {
                        "type": "object",
                        "shape": {
                          "jump": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "object",
                                  "shape": {
                                    "_meta": {
                                      "type": "catch",
                                      "inner": {
                                        "type": "optional",
                                        "inner": {
                                          "type": "nullable",
                                          "inner": {
                                            "type": "record",
                                            "key": {
                                              "type": "string"
                                            },
                                            "value": {
                                              "type": "unknown"
                                            }
                                          }
                                        }
                                      },
                                      "fallback": {
                                        "absent": true
                                      }
                                    }
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          },
                          "rename": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "object",
                                  "shape": {
                                    "_meta": {
                                      "type": "catch",
                                      "inner": {
                                        "type": "optional",
                                        "inner": {
                                          "type": "nullable",
                                          "inner": {
                                            "type": "record",
                                            "key": {
                                              "type": "string"
                                            },
                                            "value": {
                                              "type": "unknown"
                                            }
                                          }
                                        }
                                      },
                                      "fallback": {
                                        "absent": true
                                      }
                                    }
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          },
                          "searchAndReplace": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "object",
                                  "shape": {
                                    "_meta": {
                                      "type": "catch",
                                      "inner": {
                                        "type": "optional",
                                        "inner": {
                                          "type": "nullable",
                                          "inner": {
                                            "type": "record",
                                            "key": {
                                              "type": "string"
                                            },
                                            "value": {
                                              "type": "unknown"
                                            }
                                          }
                                        }
                                      },
                                      "fallback": {
                                        "absent": true
                                      }
                                    }
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          },
                          "_meta": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          }
                        }
                      }
                    }
                  },
                  "fallback": {
                    "absent": true
                  }
                },
                "positionEncodings": {
                  "type": "catch",
                  "inner": {
                    "type": "optional",
                    "inner": {
                      "type": "skip-array",
                      "inner": {
                        "type": "array",
                        "element": {
                          "type": "catch",
                          "inner": {
                            "type": "union",
                            "options": [
                              {
                                "type": "literal",
                                "values": [
                                  "utf-16"
                                ]
                              },
                              {
                                "type": "literal",
                                "values": [
                                  "utf-32"
                                ]
                              },
                              {
                                "type": "literal",
                                "values": [
                                  "utf-8"
                                ]
                              }
                            ]
                          },
                          "fallback": {
                            "skip": true
                          }
                        }
                      }
                    }
                  },
                  "fallback": {
                    "value": []
                  }
                },
                "_meta": {
                  "type": "catch",
                  "inner": {
                    "type": "optional",
                    "inner": {
                      "type": "nullable",
                      "inner": {
                        "type": "record",
                        "key": {
                          "type": "string"
                        },
                        "value": {
                          "type": "unknown"
                        }
                      }
                    }
                  },
                  "fallback": {
                    "absent": true
                  }
                }
              }
            }
          },
          "fallback": {
            "value": {
              "fs": {
                "readTextFile": false,
                "writeTextFile": false
              },
              "terminal": false,
              "auth": {
                "terminal": false
              }
            }
          }
        },
        "fallback": {
          "value": {
            "fs": {
              "readTextFile": false,
              "writeTextFile": false
            },
            "terminal": false,
            "auth": {
              "terminal": false
            }
          }
        }
      },
      "clientInfo": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "nullable",
            "inner": {
              "type": "object",
              "shape": {
                "name": {
                  "type": "string"
                },
                "title": {
                  "type": "catch",
                  "inner": {
                    "type": "optional",
                    "inner": {
                      "type": "nullable",
                      "inner": {
                        "type": "string"
                      }
                    }
                  },
                  "fallback": {
                    "absent": true
                  }
                },
                "version": {
                  "type": "string"
                },
                "_meta": {
                  "type": "catch",
                  "inner": {
                    "type": "optional",
                    "inner": {
                      "type": "nullable",
                      "inner": {
                        "type": "record",
                        "key": {
                          "type": "string"
                        },
                        "value": {
                          "type": "unknown"
                        }
                      }
                    }
                  },
                  "fallback": {
                    "absent": true
                  }
                }
              }
            }
          }
        },
        "fallback": {
          "absent": true
        }
      },
      "_meta": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "nullable",
            "inner": {
              "type": "record",
              "key": {
                "type": "string"
              },
              "value": {
                "type": "unknown"
              }
            }
          }
        },
        "fallback": {
          "absent": true
        }
      }
    }
  },
  "authenticate": {
    "type": "object",
    "shape": {
      "methodId": {
        "type": "string"
      },
      "_meta": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "nullable",
            "inner": {
              "type": "record",
              "key": {
                "type": "string"
              },
              "value": {
                "type": "unknown"
              }
            }
          }
        },
        "fallback": {
          "absent": true
        }
      }
    }
  },
  "session/new": {
    "type": "object",
    "shape": {
      "cwd": {
        "type": "string"
      },
      "additionalDirectories": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "skip-array",
            "inner": {
              "type": "array",
              "element": {
                "type": "catch",
                "inner": {
                  "type": "string"
                },
                "fallback": {
                  "skip": true
                }
              }
            }
          }
        },
        "fallback": {
          "value": []
        }
      },
      "mcpServers": {
        "type": "required-mcp-array",
        "element": {
          "type": "union",
          "options": [
            {
              "type": "intersection",
              "left": {
                "type": "object",
                "shape": {
                  "name": {
                    "type": "string"
                  },
                  "url": {
                    "type": "string"
                  },
                  "headers": {
                    "type": "array",
                    "element": {
                      "type": "object",
                      "shape": {
                        "name": {
                          "type": "string"
                        },
                        "value": {
                          "type": "string"
                        },
                        "_meta": {
                          "type": "catch",
                          "inner": {
                            "type": "optional",
                            "inner": {
                              "type": "nullable",
                              "inner": {
                                "type": "record",
                                "key": {
                                  "type": "string"
                                },
                                "value": {
                                  "type": "unknown"
                                }
                              }
                            }
                          },
                          "fallback": {
                            "absent": true
                          }
                        }
                      }
                    }
                  },
                  "_meta": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "record",
                          "key": {
                            "type": "string"
                          },
                          "value": {
                            "type": "unknown"
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  }
                }
              },
              "right": {
                "type": "object",
                "shape": {
                  "type": {
                    "type": "literal",
                    "values": [
                      "http"
                    ]
                  }
                }
              }
            },
            {
              "type": "intersection",
              "left": {
                "type": "object",
                "shape": {
                  "name": {
                    "type": "string"
                  },
                  "url": {
                    "type": "string"
                  },
                  "headers": {
                    "type": "array",
                    "element": {
                      "type": "object",
                      "shape": {
                        "name": {
                          "type": "string"
                        },
                        "value": {
                          "type": "string"
                        },
                        "_meta": {
                          "type": "catch",
                          "inner": {
                            "type": "optional",
                            "inner": {
                              "type": "nullable",
                              "inner": {
                                "type": "record",
                                "key": {
                                  "type": "string"
                                },
                                "value": {
                                  "type": "unknown"
                                }
                              }
                            }
                          },
                          "fallback": {
                            "absent": true
                          }
                        }
                      }
                    }
                  },
                  "_meta": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "record",
                          "key": {
                            "type": "string"
                          },
                          "value": {
                            "type": "unknown"
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  }
                }
              },
              "right": {
                "type": "object",
                "shape": {
                  "type": {
                    "type": "literal",
                    "values": [
                      "sse"
                    ]
                  }
                }
              }
            },
            {
              "type": "intersection",
              "left": {
                "type": "object",
                "shape": {
                  "name": {
                    "type": "string"
                  },
                  "serverId": {
                    "type": "string"
                  },
                  "_meta": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "record",
                          "key": {
                            "type": "string"
                          },
                          "value": {
                            "type": "unknown"
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  }
                }
              },
              "right": {
                "type": "object",
                "shape": {
                  "type": {
                    "type": "literal",
                    "values": [
                      "acp"
                    ]
                  }
                }
              }
            },
            {
              "type": "object",
              "shape": {
                "name": {
                  "type": "string"
                },
                "command": {
                  "type": "string"
                },
                "args": {
                  "type": "array",
                  "element": {
                    "type": "string"
                  }
                },
                "env": {
                  "type": "array",
                  "element": {
                    "type": "object",
                    "shape": {
                      "name": {
                        "type": "string"
                      },
                      "value": {
                        "type": "string"
                      },
                      "_meta": {
                        "type": "catch",
                        "inner": {
                          "type": "optional",
                          "inner": {
                            "type": "nullable",
                            "inner": {
                              "type": "record",
                              "key": {
                                "type": "string"
                              },
                              "value": {
                                "type": "unknown"
                              }
                            }
                          }
                        },
                        "fallback": {
                          "absent": true
                        }
                      }
                    }
                  }
                },
                "_meta": {
                  "type": "catch",
                  "inner": {
                    "type": "optional",
                    "inner": {
                      "type": "nullable",
                      "inner": {
                        "type": "record",
                        "key": {
                          "type": "string"
                        },
                        "value": {
                          "type": "unknown"
                        }
                      }
                    }
                  },
                  "fallback": {
                    "absent": true
                  }
                }
              }
            }
          ]
        }
      },
      "_meta": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "nullable",
            "inner": {
              "type": "record",
              "key": {
                "type": "string"
              },
              "value": {
                "type": "unknown"
              }
            }
          }
        },
        "fallback": {
          "absent": true
        }
      }
    }
  },
  "session/list": {
    "type": "object",
    "shape": {
      "cwd": {
        "type": "optional",
        "inner": {
          "type": "nullable",
          "inner": {
            "type": "string"
          }
        }
      },
      "cursor": {
        "type": "optional",
        "inner": {
          "type": "nullable",
          "inner": {
            "type": "string"
          }
        }
      },
      "_meta": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "nullable",
            "inner": {
              "type": "record",
              "key": {
                "type": "string"
              },
              "value": {
                "type": "unknown"
              }
            }
          }
        },
        "fallback": {
          "absent": true
        }
      }
    }
  },
  "session/resume": {
    "type": "object",
    "shape": {
      "sessionId": {
        "type": "string"
      },
      "cwd": {
        "type": "string"
      },
      "additionalDirectories": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "skip-array",
            "inner": {
              "type": "array",
              "element": {
                "type": "catch",
                "inner": {
                  "type": "string"
                },
                "fallback": {
                  "skip": true
                }
              }
            }
          }
        },
        "fallback": {
          "value": []
        }
      },
      "mcpServers": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "skip-array",
            "inner": {
              "type": "array",
              "element": {
                "type": "catch",
                "inner": {
                  "type": "union",
                  "options": [
                    {
                      "type": "intersection",
                      "left": {
                        "type": "object",
                        "shape": {
                          "name": {
                            "type": "string"
                          },
                          "url": {
                            "type": "string"
                          },
                          "headers": {
                            "type": "array",
                            "element": {
                              "type": "object",
                              "shape": {
                                "name": {
                                  "type": "string"
                                },
                                "value": {
                                  "type": "string"
                                },
                                "_meta": {
                                  "type": "catch",
                                  "inner": {
                                    "type": "optional",
                                    "inner": {
                                      "type": "nullable",
                                      "inner": {
                                        "type": "record",
                                        "key": {
                                          "type": "string"
                                        },
                                        "value": {
                                          "type": "unknown"
                                        }
                                      }
                                    }
                                  },
                                  "fallback": {
                                    "absent": true
                                  }
                                }
                              }
                            }
                          },
                          "_meta": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          }
                        }
                      },
                      "right": {
                        "type": "object",
                        "shape": {
                          "type": {
                            "type": "literal",
                            "values": [
                              "http"
                            ]
                          }
                        }
                      }
                    },
                    {
                      "type": "intersection",
                      "left": {
                        "type": "object",
                        "shape": {
                          "name": {
                            "type": "string"
                          },
                          "url": {
                            "type": "string"
                          },
                          "headers": {
                            "type": "array",
                            "element": {
                              "type": "object",
                              "shape": {
                                "name": {
                                  "type": "string"
                                },
                                "value": {
                                  "type": "string"
                                },
                                "_meta": {
                                  "type": "catch",
                                  "inner": {
                                    "type": "optional",
                                    "inner": {
                                      "type": "nullable",
                                      "inner": {
                                        "type": "record",
                                        "key": {
                                          "type": "string"
                                        },
                                        "value": {
                                          "type": "unknown"
                                        }
                                      }
                                    }
                                  },
                                  "fallback": {
                                    "absent": true
                                  }
                                }
                              }
                            }
                          },
                          "_meta": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          }
                        }
                      },
                      "right": {
                        "type": "object",
                        "shape": {
                          "type": {
                            "type": "literal",
                            "values": [
                              "sse"
                            ]
                          }
                        }
                      }
                    },
                    {
                      "type": "intersection",
                      "left": {
                        "type": "object",
                        "shape": {
                          "name": {
                            "type": "string"
                          },
                          "serverId": {
                            "type": "string"
                          },
                          "_meta": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          }
                        }
                      },
                      "right": {
                        "type": "object",
                        "shape": {
                          "type": {
                            "type": "literal",
                            "values": [
                              "acp"
                            ]
                          }
                        }
                      }
                    },
                    {
                      "type": "object",
                      "shape": {
                        "name": {
                          "type": "string"
                        },
                        "command": {
                          "type": "string"
                        },
                        "args": {
                          "type": "array",
                          "element": {
                            "type": "string"
                          }
                        },
                        "env": {
                          "type": "array",
                          "element": {
                            "type": "object",
                            "shape": {
                              "name": {
                                "type": "string"
                              },
                              "value": {
                                "type": "string"
                              },
                              "_meta": {
                                "type": "catch",
                                "inner": {
                                  "type": "optional",
                                  "inner": {
                                    "type": "nullable",
                                    "inner": {
                                      "type": "record",
                                      "key": {
                                        "type": "string"
                                      },
                                      "value": {
                                        "type": "unknown"
                                      }
                                    }
                                  }
                                },
                                "fallback": {
                                  "absent": true
                                }
                              }
                            }
                          }
                        },
                        "_meta": {
                          "type": "catch",
                          "inner": {
                            "type": "optional",
                            "inner": {
                              "type": "nullable",
                              "inner": {
                                "type": "record",
                                "key": {
                                  "type": "string"
                                },
                                "value": {
                                  "type": "unknown"
                                }
                              }
                            }
                          },
                          "fallback": {
                            "absent": true
                          }
                        }
                      }
                    }
                  ]
                },
                "fallback": {
                  "skip": true
                }
              }
            }
          }
        },
        "fallback": {
          "value": []
        }
      },
      "_meta": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "nullable",
            "inner": {
              "type": "record",
              "key": {
                "type": "string"
              },
              "value": {
                "type": "unknown"
              }
            }
          }
        },
        "fallback": {
          "absent": true
        }
      }
    }
  },
  "session/close": {
    "type": "object",
    "shape": {
      "sessionId": {
        "type": "string"
      },
      "_meta": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "nullable",
            "inner": {
              "type": "record",
              "key": {
                "type": "string"
              },
              "value": {
                "type": "unknown"
              }
            }
          }
        },
        "fallback": {
          "absent": true
        }
      }
    }
  },
  "session/set_config_option": {
    "type": "intersection",
    "left": {
      "type": "union",
      "options": [
        {
          "type": "object",
          "shape": {
            "value": {
              "type": "boolean"
            },
            "type": {
              "type": "literal",
              "values": [
                "boolean"
              ]
            }
          }
        },
        {
          "type": "object",
          "shape": {
            "value": {
              "type": "string"
            }
          }
        }
      ]
    },
    "right": {
      "type": "object",
      "shape": {
        "sessionId": {
          "type": "string"
        },
        "configId": {
          "type": "string"
        },
        "_meta": {
          "type": "catch",
          "inner": {
            "type": "optional",
            "inner": {
              "type": "nullable",
              "inner": {
                "type": "record",
                "key": {
                  "type": "string"
                },
                "value": {
                  "type": "unknown"
                }
              }
            }
          },
          "fallback": {
            "absent": true
          }
        }
      }
    }
  },
  "session/prompt": {
    "type": "object",
    "shape": {
      "sessionId": {
        "type": "string"
      },
      "prompt": {
        "type": "array",
        "element": {
          "type": "union",
          "options": [
            {
              "type": "intersection",
              "left": {
                "type": "object",
                "shape": {
                  "annotations": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "object",
                          "shape": {
                            "audience": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "skip-array",
                                    "inner": {
                                      "type": "array",
                                      "element": {
                                        "type": "catch",
                                        "inner": {
                                          "type": "union",
                                          "options": [
                                            {
                                              "type": "literal",
                                              "values": [
                                                "assistant"
                                              ]
                                            },
                                            {
                                              "type": "literal",
                                              "values": [
                                                "user"
                                              ]
                                            }
                                          ]
                                        },
                                        "fallback": {
                                          "skip": true
                                        }
                                      }
                                    }
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "lastModified": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "string"
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "priority": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "number",
                                    "checks": []
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "_meta": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "record",
                                    "key": {
                                      "type": "string"
                                    },
                                    "value": {
                                      "type": "unknown"
                                    }
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            }
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  },
                  "text": {
                    "type": "string"
                  },
                  "_meta": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "record",
                          "key": {
                            "type": "string"
                          },
                          "value": {
                            "type": "unknown"
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  }
                }
              },
              "right": {
                "type": "object",
                "shape": {
                  "type": {
                    "type": "literal",
                    "values": [
                      "text"
                    ]
                  }
                }
              }
            },
            {
              "type": "intersection",
              "left": {
                "type": "object",
                "shape": {
                  "annotations": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "object",
                          "shape": {
                            "audience": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "skip-array",
                                    "inner": {
                                      "type": "array",
                                      "element": {
                                        "type": "catch",
                                        "inner": {
                                          "type": "union",
                                          "options": [
                                            {
                                              "type": "literal",
                                              "values": [
                                                "assistant"
                                              ]
                                            },
                                            {
                                              "type": "literal",
                                              "values": [
                                                "user"
                                              ]
                                            }
                                          ]
                                        },
                                        "fallback": {
                                          "skip": true
                                        }
                                      }
                                    }
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "lastModified": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "string"
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "priority": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "number",
                                    "checks": []
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "_meta": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "record",
                                    "key": {
                                      "type": "string"
                                    },
                                    "value": {
                                      "type": "unknown"
                                    }
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            }
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  },
                  "data": {
                    "type": "string"
                  },
                  "mimeType": {
                    "type": "string"
                  },
                  "uri": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "string"
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  },
                  "_meta": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "record",
                          "key": {
                            "type": "string"
                          },
                          "value": {
                            "type": "unknown"
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  }
                }
              },
              "right": {
                "type": "object",
                "shape": {
                  "type": {
                    "type": "literal",
                    "values": [
                      "image"
                    ]
                  }
                }
              }
            },
            {
              "type": "intersection",
              "left": {
                "type": "object",
                "shape": {
                  "annotations": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "object",
                          "shape": {
                            "audience": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "skip-array",
                                    "inner": {
                                      "type": "array",
                                      "element": {
                                        "type": "catch",
                                        "inner": {
                                          "type": "union",
                                          "options": [
                                            {
                                              "type": "literal",
                                              "values": [
                                                "assistant"
                                              ]
                                            },
                                            {
                                              "type": "literal",
                                              "values": [
                                                "user"
                                              ]
                                            }
                                          ]
                                        },
                                        "fallback": {
                                          "skip": true
                                        }
                                      }
                                    }
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "lastModified": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "string"
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "priority": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "number",
                                    "checks": []
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "_meta": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "record",
                                    "key": {
                                      "type": "string"
                                    },
                                    "value": {
                                      "type": "unknown"
                                    }
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            }
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  },
                  "data": {
                    "type": "string"
                  },
                  "mimeType": {
                    "type": "string"
                  },
                  "_meta": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "record",
                          "key": {
                            "type": "string"
                          },
                          "value": {
                            "type": "unknown"
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  }
                }
              },
              "right": {
                "type": "object",
                "shape": {
                  "type": {
                    "type": "literal",
                    "values": [
                      "audio"
                    ]
                  }
                }
              }
            },
            {
              "type": "intersection",
              "left": {
                "type": "object",
                "shape": {
                  "annotations": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "object",
                          "shape": {
                            "audience": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "skip-array",
                                    "inner": {
                                      "type": "array",
                                      "element": {
                                        "type": "catch",
                                        "inner": {
                                          "type": "union",
                                          "options": [
                                            {
                                              "type": "literal",
                                              "values": [
                                                "assistant"
                                              ]
                                            },
                                            {
                                              "type": "literal",
                                              "values": [
                                                "user"
                                              ]
                                            }
                                          ]
                                        },
                                        "fallback": {
                                          "skip": true
                                        }
                                      }
                                    }
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "lastModified": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "string"
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "priority": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "number",
                                    "checks": []
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "_meta": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "record",
                                    "key": {
                                      "type": "string"
                                    },
                                    "value": {
                                      "type": "unknown"
                                    }
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            }
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  },
                  "description": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "string"
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  },
                  "mimeType": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "string"
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  },
                  "name": {
                    "type": "string"
                  },
                  "size": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "number",
                          "checks": []
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  },
                  "title": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "string"
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  },
                  "uri": {
                    "type": "string"
                  },
                  "_meta": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "record",
                          "key": {
                            "type": "string"
                          },
                          "value": {
                            "type": "unknown"
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  }
                }
              },
              "right": {
                "type": "object",
                "shape": {
                  "type": {
                    "type": "literal",
                    "values": [
                      "resource_link"
                    ]
                  }
                }
              }
            },
            {
              "type": "intersection",
              "left": {
                "type": "object",
                "shape": {
                  "annotations": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "object",
                          "shape": {
                            "audience": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "skip-array",
                                    "inner": {
                                      "type": "array",
                                      "element": {
                                        "type": "catch",
                                        "inner": {
                                          "type": "union",
                                          "options": [
                                            {
                                              "type": "literal",
                                              "values": [
                                                "assistant"
                                              ]
                                            },
                                            {
                                              "type": "literal",
                                              "values": [
                                                "user"
                                              ]
                                            }
                                          ]
                                        },
                                        "fallback": {
                                          "skip": true
                                        }
                                      }
                                    }
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "lastModified": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "string"
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "priority": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "number",
                                    "checks": []
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            },
                            "_meta": {
                              "type": "catch",
                              "inner": {
                                "type": "optional",
                                "inner": {
                                  "type": "nullable",
                                  "inner": {
                                    "type": "record",
                                    "key": {
                                      "type": "string"
                                    },
                                    "value": {
                                      "type": "unknown"
                                    }
                                  }
                                }
                              },
                              "fallback": {
                                "absent": true
                              }
                            }
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  },
                  "resource": {
                    "type": "union",
                    "options": [
                      {
                        "type": "object",
                        "shape": {
                          "mimeType": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "string"
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          },
                          "text": {
                            "type": "string"
                          },
                          "uri": {
                            "type": "string"
                          },
                          "_meta": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          }
                        }
                      },
                      {
                        "type": "object",
                        "shape": {
                          "blob": {
                            "type": "string"
                          },
                          "mimeType": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "string"
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          },
                          "uri": {
                            "type": "string"
                          },
                          "_meta": {
                            "type": "catch",
                            "inner": {
                              "type": "optional",
                              "inner": {
                                "type": "nullable",
                                "inner": {
                                  "type": "record",
                                  "key": {
                                    "type": "string"
                                  },
                                  "value": {
                                    "type": "unknown"
                                  }
                                }
                              }
                            },
                            "fallback": {
                              "absent": true
                            }
                          }
                        }
                      }
                    ]
                  },
                  "_meta": {
                    "type": "catch",
                    "inner": {
                      "type": "optional",
                      "inner": {
                        "type": "nullable",
                        "inner": {
                          "type": "record",
                          "key": {
                            "type": "string"
                          },
                          "value": {
                            "type": "unknown"
                          }
                        }
                      }
                    },
                    "fallback": {
                      "absent": true
                    }
                  }
                }
              },
              "right": {
                "type": "object",
                "shape": {
                  "type": {
                    "type": "literal",
                    "values": [
                      "resource"
                    ]
                  }
                }
              }
            }
          ]
        }
      },
      "_meta": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "nullable",
            "inner": {
              "type": "record",
              "key": {
                "type": "string"
              },
              "value": {
                "type": "unknown"
              }
            }
          }
        },
        "fallback": {
          "absent": true
        }
      }
    }
  },
  "session/cancel": {
    "type": "object",
    "shape": {
      "sessionId": {
        "type": "string"
      },
      "_meta": {
        "type": "catch",
        "inner": {
          "type": "optional",
          "inner": {
            "type": "nullable",
            "inner": {
              "type": "record",
              "key": {
                "type": "string"
              },
              "value": {
                "type": "unknown"
              }
            }
          }
        },
        "fallback": {
          "absent": true
        }
      }
    }
  }
}
''' )
