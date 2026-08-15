package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
)

const (
	fixtureSchema       = "dev.vibescreen.channel-security-fixture/v1"
	identityDomain      = "vibescreen/identity/v1"
	rotationDomain      = "vibescreen/traffic-key-update/v1"
	legacyMaterialBytes = 128
	materialBytes       = 256
	headerBytes         = 51
)

type channelFixture struct {
	Schema  string `json:"schema"`
	Session struct {
		ID    string `json:"id"`
		Epoch uint64 `json:"epoch"`
	} `json:"session"`
	Input struct {
		SharedSecret    string `json:"shared_secret"`
		BootstrapSecret string `json:"bootstrap_secret"`
		Context         string `json:"context"`
		RotationNonce   string `json:"rotation_nonce"`
	} `json:"input"`
	Initial keyFixture               `json:"initial"`
	Rotated keyFixture               `json:"rotated"`
	Records map[string]recordFixture `json:"records"`
}

type keyFixture struct {
	KeyID string `json:"key_id"`
	Keys  string `json:"keys"`
}

type recordFixture struct {
	Payload string `json:"payload"`
	Record  string `json:"record"`
}

type recordContract struct {
	sender  byte
	channel byte
}

var recordContracts = map[string]recordContract{
	"host_control": {sender: 1, channel: 1},
	"device_media": {sender: 2, channel: 2},
	"host_audio":   {sender: 1, channel: 3},
	"device_bulk":  {sender: 2, channel: 4},
}

func main() {
	fixturePath := flag.String("fixture", "", "path to the channel security JSON fixture")
	flag.Parse()
	if *fixturePath == "" || flag.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "usage: channel_security_fixture_verifier --fixture PATH")
		os.Exit(2)
	}
	if err := verifyFixture(*fixturePath); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func verifyFixture(path string) error {
	encoded, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("read fixture: %w", err)
	}
	var fixture channelFixture
	if err := json.Unmarshal(encoded, &fixture); err != nil {
		return fmt.Errorf("decode fixture: %w", err)
	}
	if fixture.Schema != fixtureSchema {
		return fmt.Errorf("unexpected fixture schema %q", fixture.Schema)
	}

	sharedSecret, err := decodeHex("shared secret", fixture.Input.SharedSecret)
	if err != nil {
		return err
	}
	bootstrapSecret, err := decodeExactHex("bootstrap secret", fixture.Input.BootstrapSecret, 32)
	if err != nil {
		return err
	}
	context, err := decodeExactHex("context", fixture.Input.Context, 32)
	if err != nil {
		return err
	}
	rotationNonce, err := decodeHex("rotation nonce", fixture.Input.RotationNonce)
	if err != nil {
		return err
	}
	if len(sharedSecret) == 0 || len(rotationNonce) < 16 {
		return fmt.Errorf("fixture inputs violate the key-derivation contract")
	}

	initialMaterial := hkdfSHA256(sharedSecret, bootstrapSecret, context, materialBytes)
	if err := verifyKeys("initial", fixture.Initial, initialMaterial, context); err != nil {
		return err
	}
	rotationContext := transcriptDigest(
		rotationDomain,
		[]byte(fixture.Initial.KeyID),
		uint64Bytes(1),
		uint64Bytes(2),
		rotationNonce,
	)
	rotatedMaterial := hkdfSHA256(
		initialMaterial[:legacyMaterialBytes],
		rotationNonce,
		rotationContext,
		materialBytes,
	)
	if err := verifyKeys("rotated", fixture.Rotated, rotatedMaterial, rotationContext); err != nil {
		return err
	}
	return verifyRecords(fixture, initialMaterial)
}

func verifyKeys(label string, fixture keyFixture, material, context []byte) error {
	expected, err := decodeExactHex(label+" keys", fixture.Keys, materialBytes)
	if err != nil {
		return err
	}
	if !bytes.Equal(material, expected) {
		return fmt.Errorf("%s HKDF material does not match", label)
	}
	if keyID(context, material) != fixture.KeyID {
		return fmt.Errorf("%s key ID does not match", label)
	}
	unique := make(map[string]struct{}, 8)
	for offset := 0; offset < materialBytes; offset += 32 {
		unique[string(material[offset:offset+32])] = struct{}{}
	}
	if len(unique) != 8 {
		return fmt.Errorf("%s material does not contain eight distinct directional keys", label)
	}
	return nil
}

func verifyRecords(fixture channelFixture, material []byte) error {
	if len(fixture.Records) != len(recordContracts) {
		return fmt.Errorf("fixture must contain exactly four channel records")
	}
	sessionHash := sha256.Sum256([]byte(fixture.Session.ID))
	for name, contract := range recordContracts {
		recordFixture, ok := fixture.Records[name]
		if !ok {
			return fmt.Errorf("fixture record %q is missing", name)
		}
		payload, err := decodeHex(name+" payload", recordFixture.Payload)
		if err != nil {
			return err
		}
		record, err := decodeHex(name+" record", recordFixture.Record)
		if err != nil {
			return err
		}
		if len(record) != headerBytes+len(payload)+16 {
			return fmt.Errorf("%s record length does not match its payload", name)
		}
		header, sealed := record[:headerBytes], record[headerBytes:]
		if !bytes.Equal(header[:4], []byte("VSCR")) || header[4] != 1 ||
			!bytes.Equal(header[5:21], sessionHash[:16]) ||
			binary.BigEndian.Uint64(header[21:29]) != fixture.Session.Epoch ||
			binary.BigEndian.Uint64(header[29:37]) != 1 ||
			header[37] != contract.sender || header[38] != contract.channel ||
			binary.BigEndian.Uint32(header[39:43]) != uint32(contract.channel) ||
			binary.BigEndian.Uint64(header[43:51]) != 1 {
			return fmt.Errorf("%s authenticated header does not match the record contract", name)
		}
		keyOffset := (int(contract.channel)-1)*64 + (int(contract.sender)-1)*32
		block, err := aes.NewCipher(material[keyOffset : keyOffset+32])
		if err != nil {
			return fmt.Errorf("%s AES key: %w", name, err)
		}
		gcm, err := cipher.NewGCM(block)
		if err != nil {
			return fmt.Errorf("%s AES-GCM: %w", name, err)
		}
		nonce := header[39:51]
		opened, err := gcm.Open(nil, nonce, sealed, header)
		if err != nil || !bytes.Equal(opened, payload) {
			return fmt.Errorf("%s AES-GCM record does not authenticate: %w", name, err)
		}
		if !bytes.Equal(gcm.Seal(nil, nonce, payload, header), sealed) {
			return fmt.Errorf("%s AES-GCM ciphertext does not reproduce", name)
		}
		for offset := 0; offset < materialBytes; offset += 32 {
			if offset == keyOffset {
				continue
			}
			wrongBlock, err := aes.NewCipher(material[offset : offset+32])
			if err != nil {
				return fmt.Errorf("%s alternate AES key: %w", name, err)
			}
			wrongGCM, err := cipher.NewGCM(wrongBlock)
			if err != nil {
				return fmt.Errorf("%s alternate AES-GCM: %w", name, err)
			}
			if _, err := wrongGCM.Open(nil, nonce, sealed, header); err == nil {
				return fmt.Errorf("%s authenticates with directional key at offset %d", name, offset)
			}
		}
	}
	return nil
}

func hkdfSHA256(secret, salt, info []byte, size int) []byte {
	extract := hmac.New(sha256.New, salt)
	extract.Write(secret)
	prk := extract.Sum(nil)
	output := make([]byte, 0, size)
	var previous []byte
	for counter := byte(1); len(output) < size; counter++ {
		expand := hmac.New(sha256.New, prk)
		expand.Write(previous)
		expand.Write(info)
		expand.Write([]byte{counter})
		previous = expand.Sum(nil)
		output = append(output, previous...)
	}
	return output[:size]
}

func keyID(context, material []byte) string {
	firstHasher := sha256.New()
	firstHasher.Write(context)
	firstHasher.Write(material[:legacyMaterialBytes])
	second := sha256.Sum256(firstHasher.Sum(nil))
	return hex.EncodeToString(second[:])
}

func transcriptDigest(domain string, parts ...[]byte) []byte {
	encoded := lengthPrefixed([]byte(identityDomain))
	encoded = append(encoded, lengthPrefixed([]byte(domain))...)
	for _, part := range parts {
		encoded = append(encoded, lengthPrefixed(part)...)
	}
	digest := sha256.Sum256(encoded)
	return digest[:]
}

func lengthPrefixed(value []byte) []byte {
	encoded := uint64Bytes(uint64(len(value)))
	return append(encoded, value...)
}

func uint64Bytes(value uint64) []byte {
	encoded := make([]byte, 8)
	binary.BigEndian.PutUint64(encoded, value)
	return encoded
}

func decodeHex(label, value string) ([]byte, error) {
	decoded, err := hex.DecodeString(value)
	if err != nil {
		return nil, fmt.Errorf("decode %s: %w", label, err)
	}
	return decoded, nil
}

func decodeExactHex(label, value string, size int) ([]byte, error) {
	decoded, err := decodeHex(label, value)
	if err != nil {
		return nil, err
	}
	if len(decoded) != size {
		return nil, fmt.Errorf("%s must be %d bytes", label, size)
	}
	return decoded, nil
}
